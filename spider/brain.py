"""The model route (OpenAI or Claude): answers questions with the current file and test output as context.

Edits come back as a proposal only. Nothing is written until you approve it.
"""
import difflib

from .memory import extract_proposals
import os
import re
import time

from PyQt5.QtCore import QThread, pyqtSignal

EDIT_RE = re.compile(r"```edit\s+path=([^\s`]+)\s*\n(.*?)```", re.S)

RULES = """You help the user with the code in their project. Context about their current file and latest test run is below.

If, and only if, a code change would clearly help (for example they ask for a fix), propose it with exactly one block in this form:
```edit path=<path relative to the project folder>
<the complete new contents of that file>
```
Put your short explanation outside the block. Never say you have changed anything: the user reviews and approves every edit themselves.

Learning about the user: if they reveal something lasting that would help you help them later (how they like answers, tools and libraries they prefer, what their projects are, how they work), you may end your reply with up to two lines of the form
remember: <one short fact, written about the user, e.g. "Prefers pytest over unittest">
Only propose facts they actually stated or clearly showed. Never propose secrets, keys, passwords, health, money or anything about other people. The user decides whether each fact is kept."""


TREE_SKIP = {".git", "__pycache__", "node_modules", ".venv", "venv", "env", ".spider_backups",
             ".pytest_cache", ".mypy_cache", "build", "dist", ".idea", ".vscode"}


def project_overview(folder, max_files=150):
    """A compact file list plus the README, so questions work before any file is saved."""
    paths = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in TREE_SKIP and not d.startswith("."))
        for f in sorted(files):
            if f.startswith(".") and f != ".env.example":
                continue
            paths.append(os.path.relpath(os.path.join(root, f), folder).replace(os.sep, "/"))
            if len(paths) >= max_files:
                break
        if len(paths) >= max_files:
            paths.append("… (more files not listed)")
            break
    out = ["Files in the project:\n" + "\n".join(paths)] if paths else []
    for name in ("README.md", "README.rst", "README.txt", "README"):
        rp = os.path.join(folder, name)
        if os.path.isfile(rp):
            try:
                with open(rp, encoding="utf-8", errors="replace") as f:
                    txt = f.read(4000)
                out.append(f"{name} (start):\n{txt}")
            except OSError:
                pass
            break
    return "\n\n".join(out)


def build_context(folder, file_path, test_output, syntax):
    parts = []
    if folder:
        parts.append(f"Project folder: {folder}")
        overview = project_overview(folder)
        if overview:
            parts.append(overview)
    else:
        parts.append("No project folder is selected yet. If the question needs the code, tell the user "
                     "to right-click the spider and choose 'Choose project folder…'.")
    if file_path and os.path.isfile(file_path):
        rel = os.path.relpath(file_path, folder) if folder else file_path
        try:
            with open(file_path, encoding="utf-8", errors="replace") as f:
                src = f.read()
        except OSError:
            src = ""
        if len(src) > 15000:
            src = src[:15000] + "\n# … (truncated)"
        parts.append(f"Most recently saved file: {rel}\n```python\n{src}\n```")
    if syntax:
        path, line, msg = syntax
        parts.append(f"Syntax error in {os.path.relpath(path, folder) if folder else path}, line {line}: {msg}")
    if test_output:
        parts.append(f"Latest test output (tail):\n```\n{test_output[-4000:]}\n```")
    return "\n\n".join(parts) or "No project context yet."


def safe_target(folder, rel):
    """Resolve rel inside folder; refuse anything that escapes it."""
    if not folder:
        return None
    root = os.path.realpath(folder)
    target = os.path.realpath(os.path.join(root, rel))
    if target == root or not target.startswith(root + os.sep):
        return None
    return target


def make_diff(target, new_text, rel):
    try:
        with open(target, encoding="utf-8", errors="replace") as f:
            old = f.read()
    except OSError:
        old = ""
    diff = difflib.unified_diff(old.splitlines(), new_text.splitlines(),
                                fromfile=f"a/{rel}", tofile=f"b/{rel}", lineterm="", n=2)
    return "\n".join(diff)


def apply_edit(folder, target, new_text):
    """Back up the old file, then write the new one. Returns the backup path."""
    backup_dir = os.path.join(folder, ".spider_backups")
    os.makedirs(backup_dir, exist_ok=True)
    backup = ""
    if os.path.exists(target):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(backup_dir, f"{os.path.basename(target)}.{stamp}.bak")
        with open(target, "rb") as src, open(backup, "wb") as dst:
            dst.write(src.read())
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(new_text if new_text.endswith("\n") else new_text + "\n")
    return backup


class Ask(QThread):
    answered = pyqtSignal(str, object)   # text, edit dict or None
    learned = pyqtSignal(list)           # facts the model suggests remembering (not yet saved)
    failed = pyqtSignal(str)

    def __init__(self, provider, key, model, voice, history, question, context, folder, memory_text=""):
        super().__init__()
        self.memory_text = memory_text
        self.provider, self.key, self.model, self.voice = provider, key, model, voice
        self.history, self.question, self.context, self.folder = history, question, context, folder

    def _call(self, system, msgs):
        if self.provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=self.key)
            resp = client.messages.create(model=self.model, max_tokens=4000, system=system, messages=msgs)
            return "".join(getattr(b, "text", "") for b in resp.content)
        import openai
        client = openai.OpenAI(api_key=self.key)
        resp = client.chat.completions.create(
            model=self.model, messages=[{"role": "system", "content": system}] + msgs)
        return resp.choices[0].message.content or ""

    def run(self):
        msgs = list(self.history[-8:])
        msgs.append({"role": "user", "content": f"{self.context}\n\n---\n\n{self.question}"})
        try:
            system = self.voice + ("\n\n" + self.memory_text if self.memory_text else "") + "\n\n" + RULES
            text = self._call(system, msgs).strip()
        except ImportError:
            pkg = "anthropic" if self.provider == "anthropic" else "openai"
            self.failed.emit(f"the '{pkg}' package isn't installed (pip install {pkg})")
            return
        except Exception as e:  # network, auth, model name…
            self.failed.emit(str(e)[:300])
            return
        text, facts = extract_proposals(text)
        if facts:
            self.learned.emit(facts)
        edit = None
        m = EDIT_RE.search(text)
        if m:
            rel, body = m.group(1).strip(), m.group(2)
            target = safe_target(self.folder, rel)
            if target:
                edit = {"rel": rel, "target": target, "text": body,
                        "diff": make_diff(target, body, rel)}
            text = EDIT_RE.sub("", text).strip()
            if not target:
                text += f"\n\n(I ignored an edit to '{rel}' because it's outside your project folder.)"
        self.answered.emit(text or "(no answer)", edit)
