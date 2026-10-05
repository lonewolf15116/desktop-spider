"""Stage 3: always there. Tray icon, global shortcut, start with Windows, session memory, one instance."""
import json
import os
import sys
import time

from PyQt5.QtCore import QAbstractNativeEventFilter, QLockFile, QObject, pyqtSignal
from PyQt5.QtGui import QIcon, QPainter, QPixmap
from PyQt5.QtCore import Qt

from .settings import APP_DIR

SESSION_PATH = os.path.join(APP_DIR, "session.json")
LOCK_PATH = os.path.join(APP_DIR, ".spider.lock")
STARTUP_NAME = "Desktop Spider.cmd"


# ── one spider at a time
def single_instance():
    """Return a held lock, or None if another spider is already running."""
    lock = QLockFile(LOCK_PATH)
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        return None
    return lock


# ── where you left off
def load_session(path=SESSION_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_session(history, folder, path=SESSION_PATH):
    data = {"history": history[-8:], "folder": folder, "last_seen": time.time()}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


# ── start with Windows (a small .cmd in your Startup folder; toggle removes it)
def startup_dir():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return ""
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def startup_path():
    d = startup_dir()
    return os.path.join(d, STARTUP_NAME) if d else ""


def startup_enabled():
    p = startup_path()
    return bool(p) and os.path.isfile(p)


def set_startup(on):
    """Create or remove the Startup entry. Returns (ok, message)."""
    p = startup_path()
    if not p:
        return False, "Start with Windows only works on Windows."
    if not on:
        try:
            if os.path.isfile(p):
                os.remove(p)
            return True, "removed"
        except OSError as e:
            return False, str(e)
    pyw = sys.executable
    if pyw.lower().endswith("python.exe"):
        cand = pyw[:-len("python.exe")] + "pythonw.exe"
        if os.path.isfile(cand):
            pyw = cand
    body = f'@echo off\r\ncd /d "{APP_DIR}"\r\nstart "" "{pyw}" -m spider\r\n'
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(body)
        return True, "added"
    except OSError as e:
        return False, str(e)


# ── tray icon picture: the current persona, drawn small
def persona_icon(persona, state, accent):
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate(-18, -18)          # crop the 100px drawing to the spider's body
    try:
        persona.draw(p, 100, 100, state, 0.0, (1, 1), accent)
    finally:
        p.end()
    return QIcon(pm)


# ── global shortcut (Windows). Default Ctrl+Alt+S, with fallbacks if another app already owns it.
WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000
FALLBACKS = ["ctrl+alt+s", "ctrl+alt+w", "ctrl+shift+alt+s", "ctrl+shift+alt+space"]
_MODS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}
_KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B}


def parse_hotkey(combo):
    """'ctrl+alt+s' -> (modifiers, virtual key, 'Ctrl+Alt+S'), or None if it can't be used."""
    parts = [p.strip().lower() for p in str(combo).split("+") if p.strip()]
    if len(parts) < 2:
        return None
    mods, key = 0, parts[-1]
    for p in parts[:-1]:
        if p not in _MODS:
            return None
        mods |= _MODS[p]
    if key in _KEYS:
        vk = _KEYS[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        vk = 0x6F + int(key[1:])
    else:
        return None
    if not mods & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return None                      # a bare letter or Shift+letter would hijack normal typing
    label = "+".join(p.capitalize() if p not in ("ctrl", "alt") else p.capitalize() for p in parts[:-1])
    return mods, vk, f"{label}+{key.upper() if len(key) == 1 else key.capitalize()}"


class HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id, callback):
        super().__init__()
        self.hotkey_id = hotkey_id
        self.callback = callback

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", "windows_generic_MSG"):
            import ctypes.wintypes
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                self.callback()
                return True, 0
        return False, 0


class Hotkey(QObject):
    pressed = pyqtSignal()
    ID = 0xB0B

    def __init__(self, app, preferred="ctrl+alt+s"):
        super().__init__()
        self.app = app
        self.ok = False
        self.filter = None
        self.label = ""
        self.taken = []                  # shortcuts another app already owned
        if sys.platform != "win32":
            return
        try:
            import ctypes
            self.user32 = ctypes.windll.user32
        except Exception:
            return
        for combo in [preferred] + [c for c in FALLBACKS if c != preferred]:
            parsed = parse_hotkey(combo)
            if not parsed:
                continue
            mods, vk, label = parsed
            try:
                if self.user32.RegisterHotKey(None, self.ID, mods | MOD_NOREPEAT, vk):
                    self.label = label
                    self.filter = HotkeyFilter(self.ID, self.pressed.emit)
                    app.installNativeEventFilter(self.filter)
                    self.ok = True
                    return
            except Exception:
                pass
            self.taken.append(label)

    def release(self):
        if self.ok:
            try:
                self.user32.UnregisterHotKey(None, self.ID)
            except Exception:
                pass
            self.ok = False
