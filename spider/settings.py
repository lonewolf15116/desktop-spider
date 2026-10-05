"""Settings live in settings.json next to the app, so you can also edit them by hand."""
import json
import os

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_PATH = os.path.join(APP_DIR, "settings.json")
ENV_PATH = os.path.join(APP_DIR, ".env")

DEFAULTS = {
    "persona": "vesper",            # "vesper" or "nib"
    "corner": "bottom-right",       # top-left, top-right, bottom-left, bottom-right
    "accent": "#f2a93b",            # Vesper's light, Nib's eyes
    "chattiness": "normal",         # silent, normal, talkative
    "watch_folder": "",             # project the legs watch
    "test_command": "python -m pytest -q -x -p no:cacheprovider",
    "legs": {"tests": True, "syntax": True},
    "model": "claude-sonnet-5-5",
    "long_session_hours": 3,
    "focus": False,
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


def api_key():
    """ANTHROPIC_API_KEY from the environment, or from a .env file next to the app."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""
