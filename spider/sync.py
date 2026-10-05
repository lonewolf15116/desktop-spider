"""Stage 4a: memory that follows you. Syncs memory.json through a folder you own.

Pick a folder that your cloud drive already syncs (OneDrive, Google Drive, Dropbox) or a USB stick.
Every spider you install and point at the same folder shares one memory. Nothing else is synced,
and nothing leaves your machines except through that folder.

Merging: union of facts by id, minus anything forgotten on any device (forgotten ids are kept as
tombstones), with duplicate wording collapsed to the oldest copy.
"""
import json
import os

from .memory import _norm

SUBDIR = "desktop-spider"
FILE = "memory.json"


def remote_path(folder):
    return os.path.join(folder, SUBDIR, FILE)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("items", []), d.get("forgotten", [])
    except (OSError, ValueError, AttributeError):
        return [], []


def merge(local_items, local_forgotten, remote_items, remote_forgotten):
    forgotten = list(dict.fromkeys(list(local_forgotten) + list(remote_forgotten)))
    gone = set(forgotten)
    by_id = {}
    for item in list(remote_items) + list(local_items):
        if isinstance(item, dict) and item.get("id") and item.get("text") and item["id"] not in gone:
            by_id.setdefault(item["id"], item)
    seen, out = set(), []
    for item in sorted(by_id.values(), key=lambda i: (i.get("added", ""), i["id"])):
        key = _norm(item["text"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out, forgotten[-1000:]


def sync(memory, folder):
    """Merge memory with the copy in folder and write both. Returns (ok, message, changed_locally)."""
    if not folder or not os.path.isdir(folder):
        return False, "Sync folder not found.", False
    path = remote_path(folder)
    r_items, r_forgotten = _read(path)
    before = [i["id"] for i in memory.items]
    items, forgotten = merge(memory.items, memory.forgotten, r_items, r_forgotten)
    memory.items, memory.forgotten = items, forgotten
    memory.save()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"items": items, "forgotten": forgotten}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        return False, f"Couldn't write to the sync folder: {e}", before != [i["id"] for i in items]
    return True, f"{len(items)} memories in sync.", before != [i["id"] for i in items]
