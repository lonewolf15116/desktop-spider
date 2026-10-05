"""Legs: lightweight watchers on a project folder. Plain code only, no model calls.

- syntax leg: compiles every changed .py file the moment you save it
- tests leg:  runs your test command after a save and reads the result
"""
import os
import re
import shlex
import sys
import time

from PyQt5.QtCore import QObject, QProcess, QTimer, pyqtSignal

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "env", ".mypy_cache",
             ".pytest_cache", "build", "dist", ".idea", ".vscode", ".spider_backups"}
MAX_FILES = 4000


def scan(folder):
    """Return {path: mtime} for .py files under folder (bounded)."""
    out = {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                try:
                    out[path] = os.path.getmtime(path)
                except OSError:
                    pass
                if len(out) >= MAX_FILES:
                    return out
    return out


def check_syntax(path):
    """Return None if the file compiles, else (line, message)."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            src = f.read()
        compile(src, path, "exec")
        return None
    except SyntaxError as e:
        return (e.lineno or 0, e.msg or "syntax error")
    except (OSError, ValueError):
        return None


def parse_pytest(output, exit_code):
    """Summarise pytest output: state, counts, first failing test and line."""
    passed = sum(int(n) for n in re.findall(r"(\d+) passed", output))
    failed = sum(int(n) for n in re.findall(r"(\d+) failed", output))
    errors = sum(int(n) for n in re.findall(r"(\d+) errors?\b", output))
    first = re.search(r"^(?:FAILED|ERROR) (\S+)", output, re.M)
    test = first.group(1).split("::")[-1] if first else ""
    lines = re.findall(r"^(\S+\.py):(\d+): ", output, re.M)
    line = lines[-1][1] if lines else ""
    if exit_code == 5 or (passed == 0 and failed == 0 and errors == 0 and "no tests ran" in output):
        state = "none"
    elif exit_code == 0:
        state = "pass"
    else:
        state = "fail"
    return {"state": state, "passed": passed, "failed": failed + errors,
            "test": test or "a test", "line": line}


class Legs(QObject):
    leg_changed = pyqtSignal(str, str, dict)   # leg name, state, info
    file_saved = pyqtSignal(str)               # most recently changed file

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.snapshot = {}
        self.last_file = ""
        self.last_output = ""
        self.last_syntax = None
        self.proc = None
        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.run_tests)
        self.kill_timer = QTimer(self)
        self.kill_timer.setSingleShot(True)
        self.kill_timer.timeout.connect(self._kill)

    @property
    def folder(self):
        f = self.settings.get("watch_folder", "")
        return f if f and os.path.isdir(f) else ""

    def start(self):
        self.snapshot = scan(self.folder) if self.folder else {}
        self.poll.start(1500)

    def _poll(self):
        if not self.folder:
            return
        now = scan(self.folder)
        changed = [p for p, m in now.items() if self.snapshot.get(p) != m]
        self.snapshot = now
        if not changed:
            return
        changed.sort(key=lambda p: now[p], reverse=True)
        self.last_file = changed[0]
        self.file_saved.emit(self.last_file)
        if self.settings["legs"].get("syntax", True):
            for path in changed[:20]:
                bad = check_syntax(path)
                if bad:
                    self.last_syntax = (path, bad[0], bad[1])
                    self.leg_changed.emit("syntax", "fail", {
                        "file": os.path.relpath(path, self.folder), "line": bad[0], "msg": bad[1]})
                    return      # don't run tests on a file that can't compile
            if self.last_syntax:
                self.last_syntax = None
            self.leg_changed.emit("syntax", "pass", {})
        if self.settings["legs"].get("tests", True):
            self.debounce.start(800)

    def run_tests(self):
        if not self.folder or not self.settings["legs"].get("tests", True):
            return
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.debounce.start(1500)     # try again once the current run finishes
            return
        parts = shlex.split(self.settings.get("test_command", ""), posix=(os.name != "nt"))
        if not parts:
            return
        if parts[0] in ("python", "python3", "py"):
            parts[0] = sys.executable.replace("pythonw.exe", "python.exe")
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(self.folder)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.finished.connect(self._done)
        self.leg_changed.emit("tests", "running", {})
        self._started = time.time()
        self.proc.start(parts[0], parts[1:])
        self.kill_timer.start(120_000)

    def _kill(self):
        if self.proc and self.proc.state() != QProcess.NotRunning:
            self.proc.kill()

    def _done(self, code, _status):
        self.kill_timer.stop()
        out = bytes(self.proc.readAll()).decode("utf-8", errors="replace")
        self.last_output = out[-6000:]
        info = parse_pytest(out, code)
        info["seconds"] = round(time.time() - self._started, 1)
        self.leg_changed.emit("tests", info["state"], info)
