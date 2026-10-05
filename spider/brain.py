"""The model route (OpenAI or Claude): answers questions with the current file and test output as context.

Edits come back as a proposal only. Nothing is written until you approve it.
"""
import difflib
import fnmatch
import json
import os
import re
import time

from .memory import extract_proposals

from PyQt5.QtCore import QThread, pyqtSignal

EDIT_RE = re.compile(r"```edit\s+path=([^\s`]+)\s*\n(.*?)```", re.S)

RULES = """You help the user with the code in their project. A project overview, their most recently saved file and the latest test output are below.

You can look around the project before answering with three read-only tools: list_files, read_file and search_code. Use them when the answer depends on code you haven't seen: read before you suggest a change, and check how a function is used before changing it. Don't call tools for general questions.

If, and only if, a code change would clearly help (for example they ask for a fix), propose it with one block per file (at most 6 files) in this form:
```edit path=<path relative to the project folder>
<the complete new contents of that file>
```
Put your short explanation outside the blocks. Never say you have changed anything: the user reviews and approves every edit themselves.

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


def call_model(provider, key, model, system, msgs):
    """One blocking model call. Used by the chat thread and by the phone link."""
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(model=model, max_tokens=4000, system=system, messages=msgs)
        return "".join(getattr(b, "text", "") for b in resp.content)
    import openai
    client = openai.OpenAI(api_key=key)
    resp = client.chat.completions.create(model=model, messages=[{"role": "system", "content": system}] + msgs)
    return resp.choices[0].message.content or ""


def system_prompt(voice, memory_text):
    return voice + ("\n\n" + memory_text if memory_text else "") + "\n\n" + RULES


# ── project tools the model may call (read-only, confined to the project folder)
TOOL_SPECS = [
    ("list_files", "List files and folders under a directory of the project (relative path, default the project root).",
     {"type": "object", "properties": {"path": {"type": "string", "description": "Directory relative to the project root"}}}),
    ("read_file", "Read a text file from the project, optionally a line range. Returns numbered lines.",
     {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"},
                                       "end_line": {"type": "integer"}}, "required": ["path"]}),
    ("search_code", "Search the project's text files for a regular expression (case-insensitive). Returns file:line: text.",
     {"type": "object", "properties": {"pattern": {"type": "string"},
                                       "glob": {"type": "string", "description": "Optional filename filter like *.py"}},
      "required": ["pattern"]}),
]
TEXT_EXT = {".py", ".md", ".txt", ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml", ".js", ".ts", ".tsx",
            ".jsx", ".html", ".css", ".sql", ".sh", ".bat", ".ps1", ".rs", ".go", ".java", ".c", ".h", ".cpp",
            ".ipynb", ".r", ".tex", ".csv", ""}


def _rel_ok(folder, rel):
    t = safe_target(folder, rel) if rel not in ("", ".", "./") else os.path.realpath(folder)
    return t


def run_tool(folder, name, args):
    """Execute one tool call. Always returns a short string (errors included)."""
    if not folder:
        return "No project folder is selected."
    args = args if isinstance(args, dict) else {}
    try:
        if name == "list_files":
            base = _rel_ok(folder, str(args.get("path", "") or ""))
            if not base or not os.path.isdir(base):
                return "Not a folder inside the project."
            out = []
            for entry in sorted(os.listdir(base)):
                if entry in TREE_SKIP or entry.startswith("."):
                    continue
                full = os.path.join(base, entry)
                out.append(entry + ("/" if os.path.isdir(full) else ""))
            return "\n".join(out[:300]) or "(empty)"
        if name == "read_file":
            target = safe_target(folder, str(args.get("path", "")))
            if not target or not os.path.isfile(target):
                return "No such file inside the project."
            if os.path.basename(target) == ".env" or os.path.getsize(target) > 2_000_000:
                return "That file can't be read here."
            with open(target, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
            a = max(1, int(args.get("start_line") or 1))
            b = min(len(lines), int(args.get("end_line") or a + 399))
            chunk = [f"{i:5d}  {lines[i - 1]}" for i in range(a, b + 1)]
            text = "\n".join(chunk)
            if len(text) > 24000:
                text = text[:24000] + "\n… (truncated; ask for a smaller line range)"
            more = f"\n… ({len(lines) - b} more lines)" if b < len(lines) else ""
            return (text or "(empty file)") + more
        if name == "search_code":
            try:
                rx = re.compile(str(args.get("pattern", "")), re.I)
            except re.error as e:
                return f"Bad pattern: {e}"
            glob = str(args.get("glob") or "")
            hits = []
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if d not in TREE_SKIP and not d.startswith(".")]
                for fname in files:
                    if glob and not fnmatch.fnmatch(fname, glob):
                        continue
                    if os.path.splitext(fname)[1].lower() not in TEXT_EXT or fname == ".env":
                        continue
                    path = os.path.join(root, fname)
                    try:
                        with open(path, encoding="utf-8", errors="replace") as f:
                            for n, line in enumerate(f, 1):
                                if rx.search(line):
                                    rel = os.path.relpath(path, folder).replace(os.sep, "/")
                                    hits.append(f"{rel}:{n}: {line.strip()[:200]}")
                                    if len(hits) >= 80:
                                        return "\n".join(hits) + "\n… (more matches; narrow the pattern)"
                    except OSError:
                        pass
            return "\n".join(hits) or "No matches."
    except Exception as e:
        return f"Tool error: {e}"
    return f"Unknown tool {name}."


def tool_label(name, args):
    if name == "read_file":
        return f"Reading {args.get('path', '')}"
    if name == "search_code":
        return f"Searching for “{args.get('pattern', '')}”"
    return f"Looking in {args.get('path') or 'the project'}"


def parse_edits(text, folder):
    """Pull every ```edit block out of a reply. Returns (clean_text, edits, ignored_paths)."""
    edits, ignored = [], []
    for m in EDIT_RE.finditer(text):
        rel, body = m.group(1).strip(), m.group(2)
        target = safe_target(folder, rel)
        if not target or len(edits) >= 6:
            ignored.append(rel)
            continue
        edits.append({"rel": rel, "target": target, "text": body, "diff": make_diff(target, body, rel)})
    return EDIT_RE.sub("", text).strip(), edits, ignored


class Ask(QThread):
    """One question: streams the reply, lets the model use project tools, returns proposed edits."""
    partial = pyqtSignal(str)            # the whole reply so far (streams)
    activity = pyqtSignal(str)           # "Reading app.py", "Searching for …"
    answered = pyqtSignal(str, object)   # final text, list of edits (may be empty)
    learned = pyqtSignal(list)           # facts the model suggests remembering (not yet saved)
    failed = pyqtSignal(str)
    MAX_ROUNDS = 8

    def __init__(self, provider, key, model, voice, history, question, context, folder, memory_text=""):
        super().__init__()
        self.memory_text = memory_text
        self.provider, self.key, self.model, self.voice = provider, key, model, voice
        self.history, self.question, self.context, self.folder = history, question, context, folder
        self.stopped = False
        self.shown = ""

    def stop(self):
        self.stopped = True

    def _emit(self, extra):
        self.shown += extra
        self.partial.emit(self.shown)

    # OpenAI: streamed chat completions with function tools
    def _openai(self, system, msgs):
        import openai
        client = openai.OpenAI(api_key=self.key)
        convo = [{"role": "system", "content": system}] + msgs
        tools = [{"type": "function", "function": {"name": n, "description": d, "parameters": sch}}
                 for n, d, sch in TOOL_SPECS] if self.folder else None
        for _ in range(self.MAX_ROUNDS):
            kw = {"model": self.model, "messages": convo, "stream": True}
            if tools:
                kw["tools"] = tools
            stream = client.chat.completions.create(**kw)
            text, calls = "", {}
            for chunk in stream:
                if self.stopped:
                    return
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    text += delta.content
                    self._emit(delta.content)
                for tc in getattr(delta, "tool_calls", None) or []:
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        slot["name"] += getattr(fn, "name", None) or ""
                        slot["args"] += getattr(fn, "arguments", None) or ""
            if not calls:
                return
            ordered = [calls[i] for i in sorted(calls)]
            convo.append({"role": "assistant", "content": text or None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                for c in ordered]})
            for c in ordered:
                try:
                    args = json.loads(c["args"] or "{}")
                except ValueError:
                    args = {}
                self.activity.emit(tool_label(c["name"], args))
                convo.append({"role": "tool", "tool_call_id": c["id"], "content": run_tool(self.folder, c["name"], args)})
            if self.shown and not self.shown.endswith("\n"):
                self.shown = self.shown.rstrip(" ")
                self._emit("\n\n")

    # Claude: streamed messages with tool use
    def _anthropic(self, system, msgs):
        import anthropic
        client = anthropic.Anthropic(api_key=self.key)
        convo = list(msgs)
        tools = [{"name": n, "description": d, "input_schema": sch} for n, d, sch in TOOL_SPECS] if self.folder else None
        for _ in range(self.MAX_ROUNDS):
            kw = {"model": self.model, "max_tokens": 8000, "system": system, "messages": convo}
            if tools:
                kw["tools"] = tools
            with client.messages.stream(**kw) as stream:
                for piece in stream.text_stream:
                    if self.stopped:
                        return
                    self._emit(piece)
                final = stream.get_final_message()
            uses = [b for b in final.content if getattr(b, "type", "") == "tool_use"]
            if not uses:
                return
            convo.append({"role": "assistant", "content": final.content})
            results = []
            for b in uses:
                self.activity.emit(tool_label(b.name, b.input or {}))
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": run_tool(self.folder, b.name, b.input or {})})
            convo.append({"role": "user", "content": results})
            if self.shown and not self.shown.endswith("\n"):
                self.shown = self.shown.rstrip(" ")
                self._emit("\n\n")

    def run(self):
        msgs = list(self.history[-8:])
        msgs.append({"role": "user", "content": f"{self.context}\n\n---\n\n{self.question}"})
        system = system_prompt(self.voice, self.memory_text)
        try:
            (self._anthropic if self.provider == "anthropic" else self._openai)(system, msgs)
        except ImportError:
            pkg = "anthropic" if self.provider == "anthropic" else "openai"
            self.failed.emit(f"the '{pkg}' package isn't installed (pip install {pkg})")
            return
        except Exception as e:  # network, auth, model name…
            if not self.shown:
                self.failed.emit(str(e)[:300])
                return
            self.shown += f"\n\n(Interrupted: {str(e)[:160]})"
        text = self.shown.strip()
        if self.stopped:
            text += "\n\n(stopped)"
        text, facts = extract_proposals(text)
        if facts:
            self.learned.emit(facts)
        text, edits, ignored = parse_edits(text, self.folder)
        for rel in ignored:
            text += f"\n\n(I left out an edit to '{rel}': it's outside your project or over the 6-file limit.)"
        self.answered.emit(text or "(no answer)", edits)
