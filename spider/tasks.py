"""Stage 2: legs beyond code. Notes, reminders, a daily summary and paper reading.

Everything here is plain code (the green route) except paper summaries, which go to the model.
Typed commands are understood locally, without a model call:

    note: buy printer ink            note that the viva is on the 14th
    remind me in 20 min to stretch   remind me at 18:30 to call home
    reminders                        summary / what did I do today
"""
import json
import os
import re
import subprocess
import threading
import time
import uuid

from .settings import APP_DIR

NOTES_PATH = os.path.join(APP_DIR, "notes.md")
REMINDERS_PATH = os.path.join(APP_DIR, "reminders.json")
_lock = threading.Lock()          # the phone link writes from another thread


# ── command parsing
NOTE_RE = re.compile(r"^\s*(?:note|jot)(?:\s+that)?\s*[:\-]?\s+(.+)$", re.I | re.S)
REMIND_IN_RE = re.compile(
    r"^\s*remind me in\s+(\d+(?:\.\d+)?)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours)\s+(?:to\s+)?(.+)$", re.I)
REMIND_AT_RE = re.compile(r"^\s*remind me at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(?:to\s+)?(.+)$", re.I)
SUMMARY_RE = re.compile(r"^\s*(summary|daily summary|today|what did i (?:do|work on) today\??)\s*$", re.I)
LIST_REM_RE = re.compile(r"^\s*(reminders|my reminders|list reminders)\s*$", re.I)


def parse_command(text, now=None):
    """Return (kind, payload) for local commands, or None for a normal question."""
    now = now or time.time()
    m = NOTE_RE.match(text)
    if m:
        return "note", m.group(1).strip()
    m = REMIND_IN_RE.match(text)
    if m:
        n, unit, what = float(m.group(1)), m.group(2).lower(), m.group(3).strip()
        secs = n * (3600 if unit.startswith("h") else 60)
        return "remind", {"at": now + secs, "text": what.rstrip(".")}
    m = REMIND_AT_RE.match(text)
    if m:
        h, mi, ap, what = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower(), m.group(4).strip()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        if not (0 <= h < 24 and 0 <= mi < 60):
            return None
        lt = time.localtime(now)
        target = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, mi, 0, 0, 0, -1))
        if target <= now:
            target += 86400                      # that time has passed today: tomorrow
        return "remind", {"at": target, "text": what.rstrip(".")}
    if SUMMARY_RE.match(text):
        return "summary", None
    if LIST_REM_RE.match(text):
        return "list_reminders", None
    return None


# ── notes
def add_note(text, path=NOTES_PATH):
    line = f"- {time.strftime('%Y-%m-%d %H:%M')}  {' '.join(text.split())}\n"
    with _lock:
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            if new:
                f.write("# Notes\n\n")
            f.write(line)
    return line.strip()


def recent_notes(n=5, path=NOTES_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return [l.strip() for l in f if l.startswith("- ")][-n:]
    except OSError:
        return []


# ── reminders
class Reminders:
    def __init__(self, path=REMINDERS_PATH):
        self.path = path
        self.items = []
        try:
            with open(path, encoding="utf-8") as f:
                self.items = json.load(f).get("items", [])
        except (OSError, ValueError):
            pass

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"items": self.items}, f, indent=2)

    def add(self, at, text):
        with _lock:
            item = {"id": uuid.uuid4().hex[:8], "at": float(at), "text": text}
            self.items.append(item)
            self.items.sort(key=lambda i: i["at"])
            self._save()
        return item

    def due(self, now=None):
        """Pop and return reminders whose time has come."""
        now = now or time.time()
        with _lock:
            ready = [i for i in self.items if i["at"] <= now]
            if ready:
                self.items = [i for i in self.items if i["at"] > now]
                self._save()
        return ready

    def upcoming(self):
        return list(self.items)

    def cancel(self, item_id):
        with _lock:
            n = len(self.items)
            self.items = [i for i in self.items if i["id"] != item_id]
            if len(self.items) != n:
                self._save()
                return True
        return False


def when_text(ts, now=None):
    now = now or time.time()
    d = ts - now
    if d < 3600:
        return f"in {max(1, round(d / 60))} min"
    same_day = time.strftime("%Y-%m-%d", time.localtime(ts)) == time.strftime("%Y-%m-%d", time.localtime(now))
    return ("today at " if same_day else "tomorrow at ") + time.strftime("%H:%M", time.localtime(ts))


# ── daily summary (git + saves)
def _git(folder, *args):
    try:
        out = subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def git_today(folder, since="midnight"):
    """Commits and touched files since midnight in one repo."""
    if not folder or not os.path.isdir(os.path.join(folder, ".git")):
        return None
    log = _git(folder, "log", f"--since={since}", "--pretty=format:%h %s", "--no-merges")
    files = _git(folder, "log", f"--since={since}", "--name-only", "--pretty=format:")
    status = _git(folder, "status", "--porcelain")
    commits = [l for l in log.splitlines() if l.strip()]
    touched = sorted({l.strip() for l in files.splitlines() if l.strip()})
    uncommitted = [l[3:] for l in status.splitlines() if l.strip()]
    return {"commits": commits, "files": touched, "uncommitted": uncommitted}


def daily_summary(folders, saves_today=0, reminders=None, notes=None):
    """Markdown summary of today across your projects."""
    lines = [f"**Today, {time.strftime('%A %d %B')}**", ""]
    any_work = False
    for folder in folders:
        info = git_today(folder)
        name = os.path.basename(os.path.normpath(folder)) if folder else ""
        if info is None:
            continue
        if not (info["commits"] or info["uncommitted"]):
            continue
        any_work = True
        lines.append(f"**{name}**")
        if info["commits"]:
            lines.append(f"- {len(info['commits'])} commit(s): " + "; ".join(c.split(' ', 1)[-1] for c in info["commits"][:6]))
        if info["files"]:
            lines.append(f"- files touched: {', '.join(info['files'][:8])}" + (" …" if len(info["files"]) > 8 else ""))
        if info["uncommitted"]:
            lines.append(f"- {len(info['uncommitted'])} uncommitted change(s), e.g. {', '.join(info['uncommitted'][:4])}")
        lines.append("")
    if saves_today:
        lines.append(f"- {saves_today} file save(s) seen by the legs today")
    if not any_work and not saves_today:
        lines.append("Nothing committed or changed in your projects yet today.")
    if reminders:
        lines += ["", "**Coming up**"] + [f"- {when_text(r['at'])}: {r['text']}" for r in reminders[:5]]
    if notes:
        lines += ["", "**Latest notes**"] + [f"- {n[2:]}" for n in notes[-3:]]
    return "\n".join(lines).strip()


# ── papers
def pdf_text(path, max_chars=14000):
    """Extract text from a PDF. Returns (text, error)."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "Reading PDFs needs the 'pypdf' package (pip install pypdf)."
    try:
        reader = PdfReader(path)
        parts, total = [], 0
        for page in reader.pages:
            t = page.extract_text() or ""
            parts.append(t)
            total += len(t)
            if total >= max_chars:
                break
        text = "\n".join(parts)[:max_chars].strip()
        if not text:
            return "", "That PDF has no extractable text (it may be scanned images)."
        return text, ""
    except Exception as e:
        return "", f"Couldn't read that PDF: {e}"


PAPER_QUESTION = ("Summarise this paper for me in under 200 words: the problem, the key idea, how they evaluate it, "
                  "the headline result with numbers, and one limitation. Then give one sentence on how it could "
                  "relate to my own projects, if anything I've told you makes that clear.")
