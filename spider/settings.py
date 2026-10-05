"""Settings live in settings.json next to the app, so you can also edit them by hand."""
import json
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
ENV_PATH = os.path.join(APP_DIR, ".env")

DEFAULTS = {
    "persona": "zip",               # "zip", "vesper" or "nib"
    "corner": "bottom-right",       # top-left, top-right, bottom-left, bottom-right
    "accent": "#f2a93b",            # Vesper's light, Nib's eyes
    "chattiness": "normal",         # silent, normal, talkative
    "watch_folder": "",             # project the legs watch
    "test_command": "python -m pytest -q -x -p no:cacheprovider",
    "legs": {"tests": True, "syntax": True},
    "provider": "openai",           # "openai" or "anthropic"
    "openai_model": "gpt-5-mini",
    "anthropic_model": "claude-sonnet-5-5",
    "long_session_hours": 3,
    "focus": False,
    "learning": True,               # may the spider ask to remember things?
    "recent_folders": [],           # projects included in the daily summary
    "sync_folder": "",              # stage 4: folder that syncs memory between your devices
    "phone_link": False,            # stage 4: phone chat over your local network
    "phone_port": 8765,
    "tray": True,
    "hotkey": "ctrl+alt+v",          # stage 3: global shortcut; falls back if another app owns it
    "size": "small",                # small, medium, large
    "fade_when_idle": True,         # fade to a ghost after a while so it never covers your work
    "chat_geometry": [],            # where you last left the chat window
}


def load():
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            data.update(saved)
            data["legs"] = {**DEFAULTS["legs"], **saved.get("legs", {})}
    except (OSError, ValueError):
        pass
    return data


def save(data):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


PROVIDERS = {"openai": ("OPENAI_API_KEY", "OpenAI"), "anthropic": ("ANTHROPIC_API_KEY", "Claude")}


def provider(data):
    p = data.get("provider", "openai")
    return p if p in PROVIDERS else "openai"


def model_for(data):
    return data.get(f"{provider(data)}_model") or DEFAULTS[f"{provider(data)}_model"]


def api_key(prov="openai"):
    """The provider's key from the environment, or from a .env file next to the app."""
    var = PROVIDERS.get(prov, PROVIDERS["openai"])[0]
    key = os.environ.get(var, "").strip()
    if key:
        return key
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(var + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""
