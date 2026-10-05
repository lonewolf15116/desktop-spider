"""Stages 2-4: tasks, always-there helpers, sync and the phone link."""
import json
import os
import subprocess
import time
import types
import urllib.error
import urllib.request

import pytest

from spider import always, sync, tasks
from spider.memory import Memory


# ── stage 2
def test_parse_commands():
    now = time.mktime((2026, 10, 5, 22, 0, 0, 0, 0, -1))
    assert tasks.parse_command("note: buy printer ink", now) == ("note", "buy printer ink")
    assert tasks.parse_command("note that the viva is on the 14th", now) == ("note", "the viva is on the 14th")
    kind, p = tasks.parse_command("remind me in 20 min to stretch", now)
    assert kind == "remind" and p["text"] == "stretch" and p["at"] == now + 1200
    kind, p = tasks.parse_command("remind me in 2 hours to sleep", now)
    assert p["at"] == now + 7200
    kind, p = tasks.parse_command("remind me at 9am to email Dr Smith", now)     # 9am already passed -> tomorrow
    lt = time.localtime(p["at"])
    assert (lt.tm_mday, lt.tm_hour, lt.tm_min) == (6, 9, 0) and p["text"] == "email Dr Smith"
    kind, p = tasks.parse_command("remind me at 23:30 to commit", now)
    assert time.localtime(p["at"]).tm_hour == 23 and time.localtime(p["at"]).tm_mday == 5
    assert tasks.parse_command("summary", now) == ("summary", None)
    assert tasks.parse_command("what did I do today?", now) == ("summary", None)
    assert tasks.parse_command("reminders", now) == ("list_reminders", None)
    assert tasks.parse_command("how do I write a note-taking app?", now) is None
    assert tasks.parse_command("remind me at 27:00 to x", now) is None


def test_reminders_due_and_persist(tmp_path):
    p = str(tmp_path / "r.json")
    r = tasks.Reminders(p)
    a = r.add(time.time() - 1, "past")
    r.add(time.time() + 3600, "future")
    assert [i["text"] for i in r.due()] == ["past"]
    assert [i["text"] for i in tasks.Reminders(p).upcoming()] == ["future"]
    assert not r.cancel(a["id"]) and r.cancel(r.upcoming()[0]["id"]) and r.upcoming() == []


def test_notes(tmp_path):
    p = str(tmp_path / "notes.md")
    tasks.add_note("first   idea", p)
    tasks.add_note("second idea", p)
    assert open(p).read().startswith("# Notes")
    assert tasks.recent_notes(5, p)[-1].endswith("second idea") and "first idea" in tasks.recent_notes(5, p)[0]


def test_daily_summary_from_git(tmp_path):
    repo = tmp_path / "PaperTrail"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (repo / "app.py").write_text("x = 1\n")
    run("add", ".")
    run("commit", "-qm", "Add retrieval endpoint")
    (repo / "wip.py").write_text("y = 2\n")
    out = tasks.daily_summary([str(repo), str(tmp_path / "missing")], saves_today=7,
                              reminders=[{"at": time.time() + 600, "text": "stretch"}], notes=["- 2026 idea"])
    assert "**PaperTrail**" in out and "Add retrieval endpoint" in out and "app.py" in out
    assert "uncommitted" in out and "7 file save" in out and "stretch" in out and "idea" in out


def test_pdf_text_errors(tmp_path):
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(200, 200)
    p = tmp_path / "blank.pdf"
    with open(p, "wb") as f:
        w.write(f)
    text, err = tasks.pdf_text(str(p))
    assert text == "" and "no extractable text" in err
    assert "Couldn't read" in tasks.pdf_text(str(tmp_path / "nope.pdf"))[1]


# ── stage 3
def test_session_roundtrip(tmp_path):
    p = str(tmp_path / "s.json")
    always.save_session([{"role": "user", "content": str(i)} for i in range(12)], "/x/proj", p)
    s = always.load_session(p)
    assert len(s["history"]) == 8 and s["history"][-1]["content"] == "11" and s["folder"] == "/x/proj"
    assert always.load_session(str(tmp_path / "none.json")) == {}


def test_startup_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert not always.startup_enabled()
    assert always.set_startup(True)[0] and always.startup_enabled()
    body = open(always.startup_path(), encoding="utf-8", newline="").read()
    assert "-m spider" in body and "\r\n" in body
    assert always.set_startup(False)[0] and not always.startup_enabled()
    monkeypatch.delenv("APPDATA")
    assert always.set_startup(True)[0] is False


# ── stage 4: sync
def test_sync_two_devices_with_forgetting(tmp_path):
    shared = tmp_path / "OneDrive"
    shared.mkdir()
    laptop = Memory(str(tmp_path / "laptop.json"))
    desktop = Memory(str(tmp_path / "desktop.json"))
    laptop.add("Prefers pytest")
    desktop.add("Uses VS Code")
    desktop.add("prefers pytest")                         # same fact in other words -> collapsed
    assert sync.sync(laptop, str(shared))[0]
    assert sync.sync(desktop, str(shared))[0]
    sync.sync(laptop, str(shared))
    texts = lambda m: sorted(i["text"].lower() for i in m.items)
    assert texts(laptop) == texts(desktop) == ["prefers pytest", "uses vs code"]
    gone = [i for i in desktop.items if i["text"] == "Uses VS Code"][0]["id"]
    desktop.forget(gone)
    sync.sync(desktop, str(shared))
    sync.sync(laptop, str(shared))                        # forgetting on one device reaches the other
    assert texts(laptop) == ["prefers pytest"]
    assert not sync.sync(laptop, str(tmp_path / "missing"))[0]


# ── stage 4: phone link
class FakeWindow:
    def __init__(self, tmp):
        self.persona = types.SimpleNamespace(name="Vesper", voice="You are Vesper.")
        self.s = {"provider": "openai", "openai_model": "m"}
        self.legs = types.SimpleNamespace(folder=str(tmp), last_file="", last_output="", last_syntax=None)
        self.memory = Memory(str(tmp / "mem.json"))
        self.reminders = tasks.Reminders(str(tmp / "rem.json"))
        self.notes_path = str(tmp / "notes.md")
        self.st = types.SimpleNamespace(mode="idle", legs={"tests": "pass"})

    def summary_text(self):
        return "**Today** nothing yet"


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _req(url, data=None, cookie=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json", **({"Cookie": cookie} if cookie else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read().decode()


@pytest.fixture
def link(tmp_path, monkeypatch):
    from spider import phone
    monkeypatch.setattr(phone.cfg, "api_key", lambda prov: "k")
    calls = []

    def fake_model(provider, key, model, system, msgs):
        calls.append(system)
        return "Here you go.\nremember: Codes on the train"
    monkeypatch.setattr(phone, "call_model", fake_model)
    w = FakeWindow(tmp_path)
    pl = phone.PhoneLink(w, port=_free_port(), devices_path=str(tmp_path / "devices.json"))
    ok, _ = pl.start(host="127.0.0.1")
    assert ok
    pl.base = f"http://127.0.0.1:{pl.port}"
    pl.calls, pl.win = calls, w
    yield pl
    pl.stop()


def test_phone_pairing_and_auth(link):
    s, _, page = _req(link.base + "/")
    assert s == 200 and "Vesper" in page
    assert json.loads(_req(link.base + "/api/status")[2]) == {"paired": False}
    assert _req(link.base + "/api/ask", {"q": "hi"})[0] == 401
    assert _req(link.base + "/api/pair", {"code": "000000" if link.code != "000000" else "111111"})[0] == 403
    code = link.code
    s, h, _ = _req(link.base + "/api/pair", {"code": code, "name": "iPhone"})
    assert s == 200
    cookie = h["Set-Cookie"].split(";")[0]
    assert link.code != code                                  # a code works once
    assert _req(link.base + "/api/pair", {"code": code})[0] == 403
    st = json.loads(_req(link.base + "/api/status", cookie=cookie)[2])
    assert st["paired"] and st["tests"] == "pass"
    # the token is stored only as a hash
    assert cookie.split("=")[1] not in open(link.devices_path).read()


def test_phone_lockout_after_wrong_codes(link):
    first = link.code
    for _ in range(5):
        _req(link.base + "/api/pair", {"code": "x"})
    assert link.code != first


def test_phone_commands_and_model(link):
    token = link.pair(link.code, "phone")
    cookie = f"spider_token={token}"
    ask = lambda q: json.loads(_req(link.base + "/api/ask", {"q": q}, cookie)[2])["text"]
    assert ask("note: buy ink") == "Noted." and "buy ink" in open(link.win.notes_path).read()
    assert "remind you" in ask("remind me in 10 min to stretch") and link.win.reminders.upcoming()[0]["text"] == "stretch"
    assert "stretch" in ask("reminders")
    assert ask("summary").startswith("**Today**")
    link.win.memory.add("Prefers short answers")
    offers = []
    link.offer.connect(offers.append)
    assert link.answer("explain decorators") == "Here you go."       # same thread: offer arrives directly
    assert "Prefers short answers" in link.calls[-1]                  # memory travels with phone questions
    assert offers == ["Codes on the train"]
    assert "ask you on your laptop" in link.answer("remember that I like dark mode")
    assert "secret" in link.answer("remember that my token is sk-abcdefghijklmnopqrstu")
    link.unpair_all()
    assert _req(link.base + "/api/ask", {"q": "hi"}, cookie)[0] == 401


def test_parse_hotkey():
    assert always.parse_hotkey("ctrl+alt+s") == (0x0002 | 0x0001, ord("S"), "Ctrl+Alt+S")
    assert always.parse_hotkey("Ctrl+Shift+Alt+Space")[1] == 0x20
    assert always.parse_hotkey("ctrl+alt+f9")[1] == 0x78
    assert always.parse_hotkey("shift+a") is None          # would hijack typing
    assert always.parse_hotkey("s") is None and always.parse_hotkey("ctrl+banana") is None
    assert always.parse_hotkey("hyper+s") is None
