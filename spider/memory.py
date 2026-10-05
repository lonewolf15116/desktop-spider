"""Memory: what the spider knows about you.

Stored in memory.json next to the app, as plain JSON you can read or edit.
Nothing is added without your approval, and secrets are never stored.

Two sources:
  told     - you said it (in chat, or "remember that ...")
  noticed  - the spider saw a pattern (working hours, main project) and asked you first
"""
import json
import os
import re
import time
import uuid

from .settings import APP_DIR

MEMORY_PATH = os.path.join(APP_DIR, "memory.json")
STATS_PATH = os.path.join(APP_DIR, "stats.json")
MAX_ITEMS = 120
PROMPT_CHARS = 2500

KINDS = ("preference", "project", "habit", "about")

# Anything that looks like a credential stays out of memory (it would be sent to the model every time).
SECRET_PATTERNS = [
    r"\bsk-[A-Za-z0-9_\-]{10,}",                 # OpenAI-style keys
    r"\bsk-ant-[A-Za-z0-9_\-]{10,}",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",             # GitHub tokens
    r"\bAKIA[0-9A-Z]{16}\b",                     # AWS access keys
    r"\b(password|passwd|pwd|passcode|pin|api[_ ]?key|secret|token)\b\s*(is|=|:)",
    r"\b[A-Fa-f0-9]{32,}\b",                     # long hex strings
    r"\b[A-Za-z0-9+/]{40,}={0,2}",               # long base64-ish strings
    r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b",  # card-like numbers
]


def looks_secret(text):
    return any(re.search(p, text, re.I) for p in SECRET_PATTERNS)


def _norm(text):
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def guess_kind(text):
    t = text.lower()
    if any(w in t for w in ("prefer", "like", "dislike", "hate", "always", "never", "style", "short", "explain")):
        return "preference"
    if any(w in t for w in ("project", "repo", "codebase", "uses ", "built with", "stack")):
        return "project"
    if any(w in t for w in ("usually", "mostly", "between", "evenings", "mornings", "late")):
        return "habit"
    return "about"


class Memory:
    def __init__(self, path=MEMORY_PATH):
        self.path = path
        self.items = []
        self.forgotten = []          # ids you removed, so a synced copy can't bring them back
        self.load()

    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.items = [i for i in data.get("items", []) if isinstance(i, dict) and i.get("text")]
            self.forgotten = [x for x in data.get("forgotten", []) if isinstance(x, str)]
        except (OSError, ValueError):
            self.items, self.forgotten = [], []

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"items": self.items, "forgotten": self.forgotten[-1000:]}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    def has(self, text):
        n = _norm(text)
        return any(_norm(i["text"]) == n for i in self.items)

    def add(self, text, source="told", kind=None):
        """Add a fact. Returns (ok, reason). Call only after the user approved it."""
        text = " ".join(text.split()).strip(" .")
        if not text:
            return False, "empty"
        if len(text) > 300:
            return False, "too long"
        if looks_secret(text):
            return False, "secret"
        if self.has(text):
            return False, "duplicate"
        self.items.append({"id": uuid.uuid4().hex[:8], "text": text, "kind": kind or guess_kind(text),
                           "source": source, "added": time.strftime("%Y-%m-%d")})
        self.items = self.items[-MAX_ITEMS:]
        self.save()
        return True, "ok"

    def forget(self, item_id):
        before = len(self.items)
        self.items = [i for i in self.items if i["id"] != item_id]
        if len(self.items) != before:
            self.forgotten.append(item_id)
            self.save()
            return True
        return False

    def forget_all(self):
        self.forgotten += [i["id"] for i in self.items]
        self.items = []
        self.save()

    def as_prompt(self):
        """The block sent to the model with every question."""
        if not self.items:
            return ""
        lines, used = [], 0
        for i in reversed(self.items):          # newest first if we must trim
            line = f"- {i['text']}"
            if used + len(line) > PROMPT_CHARS:
                break
            lines.append(line)
            used += len(line) + 1
        return ("What you know about the user (they approved each of these; use them to tailor "
                "your help, don't recite them):\n" + "\n".join(reversed(lines)))


# ── learning from chat
REMEMBER_LINE = re.compile(r"^\s*remember:\s*(.+?)\s*$", re.I | re.M)
EXPLICIT = re.compile(r"^\s*(?:please\s+)?remember(?:\s+that)?[:,]?\s+(.+)$", re.I | re.S)


def extract_proposals(text):
    """Pull 'remember: ...' lines out of a model reply. Returns (clean_text, facts)."""
    facts = [m.strip(" .") for m in REMEMBER_LINE.findall(text)]
    clean = REMEMBER_LINE.sub("", text).strip()
    out = []
    for f in facts[:2]:
        if f and not looks_secret(f) and f not in out:
            out.append(f)
    return clean, out


def explicit_request(question):
    """'remember that I prefer tabs' -> 'I prefer tabs' (handled locally, no model call)."""
    m = EXPLICIT.match(question.strip())
    if not m:
        return None
    return m.group(1).strip().rstrip(".") or None


# ── noticing patterns (plain code, no model)
class Stats:
    def __init__(self, path=STATS_PATH):
        self.path = path
        self.data = {"hours": [0] * 24, "projects": {}, "asked": [], "last_offer": ""}
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                self.data.update(d)
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
        except OSError:
            pass

    def record_save(self, folder, when=None):
        when = when or time.localtime()
        self.data["hours"][when.tm_hour] += 1
        day = time.strftime("%Y-%m-%d", when)
        days = self.data.setdefault("saves_by_day", {})
        days[day] = days.get(day, 0) + 1
        for old in sorted(days)[:-30]:
            days.pop(old, None)
        if folder:
            name = os.path.basename(os.path.normpath(folder))
            days = self.data["projects"].setdefault(name, [])
            today = time.strftime("%Y-%m-%d", when)
            if today not in days:
                days.append(today)
                del days[:-60]
        self.save()

    def saves_today(self):
        return self.data.get("saves_by_day", {}).get(time.strftime("%Y-%m-%d"), 0)

    def suggestion(self, memory, today=None):
        """At most one 'noticed' fact per day, never one already asked about."""
        today = today or time.strftime("%Y-%m-%d")
        if self.data.get("last_offer") == today:
            return None
        candidates = []
        hours = self.data["hours"]
        if sum(hours) >= 40:
            best, best_n = 0, -1
            for h in range(24):                  # busiest 4-hour window, wrapping midnight
                n = sum(hours[(h + k) % 24] for k in range(4))
                if n > best_n:
                    best, best_n = h, n
            if best_n >= 0.5 * sum(hours):
                active = [(best + k) % 24 for k in range(4) if hours[(best + k) % 24] > 0]
                start, end = active[0], (active[-1] + 1) % 24
                candidates.append(f"Usually codes between {start:02d}:00 and {end:02d}:00")
        for name, days in self.data["projects"].items():
            if len(days) >= 3:
                candidates.append(f"Works on the {name} project regularly")
        for c in candidates:
            if c not in self.data["asked"] and not memory.has(c):
                self.data["asked"].append(c)
                self.data["last_offer"] = today
                self.save()
                return c
        return None
