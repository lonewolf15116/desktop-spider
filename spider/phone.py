"""Stage 4b: the phone link. Talk to your spider from your phone over your home Wi-Fi.

- Off until you switch it on (right-click → Phone link). It listens only on your local network.
- A phone must enter the 6-digit pairing code shown on your laptop. Paired phones get a private
  token, so they stay paired until you choose "Unpair all phones".
- From the phone you can chat, add notes and reminders, get today's summary and run your tests.
  Code edits and new memories are never approved from the phone: they wait on the laptop.
"""
import hashlib
import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PyQt5.QtCore import QObject, pyqtSignal

from . import settings as cfg
from . import tasks
from .brain import build_context, call_model, system_prompt
from .memory import explicit_request, extract_proposals, looks_secret

DEVICES_PATH = os.path.join(cfg.APP_DIR, "phone_devices.json")
COOKIE = "spider_token"
CODE_TTL = 600          # a pairing code lasts 10 minutes
MAX_TRIES = 5           # wrong codes before a new one is drawn


def lan_ip():
    """The laptop's address on the local network (no packets are sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class PhoneLink(QObject):
    offer = pyqtSignal(str)          # a fact to ask about on the laptop
    run_tests = pyqtSignal()
    notify = pyqtSignal(str)         # a short line for the spider to say
    reminders_changed = pyqtSignal()

    def __init__(self, window, port=8765, devices_path=DEVICES_PATH):
        super().__init__()
        self.w = window
        self.port = port
        self.devices_path = devices_path
        self.server = None
        self.thread = None
        self.code, self.code_born, self.tries = "", 0.0, 0
        self.history = []
        self.lock = threading.Lock()
        self.devices = self._load_devices()

    # ── pairing
    def _load_devices(self):
        try:
            with open(self.devices_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save_devices(self):
        try:
            with open(self.devices_path, "w", encoding="utf-8") as f:
                json.dump(self.devices, f, indent=2)
        except OSError:
            pass

    def new_code(self):
        self.code = f"{secrets.randbelow(10**6):06d}"
        self.code_born = time.time()
        self.tries = 0
        return self.code

    def current_code(self):
        if not self.code or time.time() - self.code_born > CODE_TTL:
            self.new_code()
        return self.code

    def pair(self, code, name):
        with self.lock:
            if not self.code or time.time() - self.code_born > CODE_TTL:
                return None
            if not secrets.compare_digest(str(code).strip(), self.code):
                self.tries += 1
                if self.tries >= MAX_TRIES:
                    self.new_code()
                return None
            token = secrets.token_hex(24)
            self.devices[_hash(token)] = {"name": (name or "phone")[:40], "added": time.strftime("%Y-%m-%d %H:%M")}
            self._save_devices()
            self.new_code()                      # a code works once
        self.notify.emit(f"Paired with {name or 'a phone'}.")
        return token

    def is_paired(self, token):
        return bool(token) and _hash(token) in self.devices

    def unpair_all(self):
        with self.lock:
            self.devices = {}
            self._save_devices()

    # ── server
    @property
    def running(self):
        return self.server is not None

    def url(self):
        return f"http://{lan_ip()}:{self.port}"

    def start(self, host="0.0.0.0"):
        if self.server:
            return True, self.url()
        link = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _token(self):
                for part in self.headers.get("Cookie", "").split(";"):
                    k, _, v = part.strip().partition("=")
                    if k == COOKIE:
                        return v
                return ""

            def _json(self, code, obj, cookie=None):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                if cookie:
                    self.send_header("Set-Cookie", f"{COOKIE}={cookie}; Path=/; Max-Age=31536000; SameSite=Strict; HttpOnly")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self):
                n = min(int(self.headers.get("Content-Length", 0) or 0), 20000)
                try:
                    return json.loads(self.rfile.read(n) or b"{}")
                except ValueError:
                    return {}

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    page = PAGE.replace("__NAME__", link.w.persona.name).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.end_headers()
                    self.wfile.write(page)
                elif self.path == "/api/status":
                    if not link.is_paired(self._token()):
                        return self._json(200, {"paired": False})
                    self._json(200, link.status())
                else:
                    self._json(404, {"error": "not found"})

            def do_POST(self):
                data = self._body()
                if self.path == "/api/pair":
                    token = link.pair(data.get("code", ""), data.get("name", ""))
                    if not token:
                        return self._json(403, {"error": "That code didn't match. Check the code on your laptop."})
                    return self._json(200, {"paired": True}, cookie=token)
                if not link.is_paired(self._token()):
                    return self._json(401, {"error": "Not paired."})
                if self.path == "/api/ask":
                    q = str(data.get("q", "")).strip()[:4000]
                    return self._json(200, {"text": link.answer(q) if q else ""})
                if self.path == "/api/tests":
                    link.run_tests.emit()
                    return self._json(200, {"text": "Running your tests on the laptop."})
                self._json(404, {"error": "not found"})

        try:
            self.server = ThreadingHTTPServer((host, self.port), Handler)
        except OSError as e:
            self.server = None
            return False, f"Couldn't open port {self.port}: {e}"
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.current_code()
        return True, self.url()

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

    # ── what the phone can do
    def status(self):
        w = self.w
        return {"paired": True, "persona": w.persona.name, "mode": w.st.mode,
                "tests": w.st.legs.get("tests", "idle"),
                "project": os.path.basename(w.legs.folder) if w.legs.folder else "",
                "reminders": [{"when": tasks.when_text(r["at"]), "text": r["text"]} for r in w.reminders.upcoming()[:5]]}

    def answer(self, q):
        w = self.w
        cmd = tasks.parse_command(q)
        if cmd:
            kind, payload = cmd
            if kind == "note":
                tasks.add_note(payload, w.notes_path)
                return "Noted."
            if kind == "remind":
                r = w.reminders.add(payload["at"], payload["text"])
                self.reminders_changed.emit()
                return f"I'll remind you on the laptop {tasks.when_text(r['at'])}: {r['text']}"
            if kind == "list_reminders":
                ups = w.reminders.upcoming()
                return "\n".join(f"- {tasks.when_text(r['at'])}: {r['text']}" for r in ups) or "No reminders."
            if kind == "summary":
                return w.summary_text()
        fact = explicit_request(q)
        if fact:
            if looks_secret(fact):
                return "That looks like a secret, so I won't keep it."
            self.offer.emit(fact)
            return "I'll ask you on your laptop before I keep that."
        prov = cfg.provider(w.s)
        key = cfg.api_key(prov)
        if not key:
            return "No API key is set on the laptop yet."
        ctx = build_context(w.legs.folder, w.legs.last_file, w.legs.last_output, w.legs.last_syntax)
        msgs = list(self.history[-8:]) + [{"role": "user", "content": f"{ctx}\n\n---\n\n(From my phone) {q}"}]
        try:
            text = call_model(prov, key, cfg.model_for(w.s), system_prompt(w.persona.voice, w.memory.as_prompt()), msgs)
        except Exception as e:
            return f"Something went wrong: {str(e)[:200]}"
        text, facts = extract_proposals(text.strip())
        for f in facts:
            self.offer.emit(f)
        if "```edit" in text:
            text = text.split("```edit")[0].strip() + "\n\n(I drafted a code change. Ask me on your laptop to see it and approve it.)"
        with self.lock:
            self.history += [{"role": "user", "content": q}, {"role": "assistant", "content": text}]
            self.history = self.history[-12:]
        return text


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__NAME__</title>
<style>
:root{--bg:#0f1116;--card:#171a21;--fg:#ebe6da;--dim:#8b929e;--gold:#f5c542;--line:#2a2f39}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
padding:max(16px,env(safe-area-inset-top)) 16px max(16px,env(safe-area-inset-bottom))}
h1{font-size:13px;letter-spacing:.2em;color:var(--gold);margin:4px 0 2px;text-transform:uppercase}
#sub{color:var(--dim);font-size:13px;margin-bottom:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}
#log{display:flex;flex-direction:column;gap:10px;margin-bottom:12px}
.me{align-self:flex-end;background:#26303d;border-radius:14px 14px 4px 14px;padding:8px 12px;max-width:85%}
.it{align-self:flex-start;background:var(--card);border:1px solid var(--line);border-radius:14px 14px 14px 4px;padding:10px 12px;max-width:92%;white-space:pre-wrap}
form{display:flex;gap:8px}input{flex:1;min-width:0;background:#1d212a;color:var(--fg);border:1px solid var(--line);border-radius:12px;padding:12px;font-size:16px}
button{background:var(--gold);color:#1b1505;border:0;border-radius:12px;padding:0 16px;font-weight:600;font-size:15px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 14px}.chips button{background:transparent;color:var(--fg);border:1px solid var(--line);padding:6px 10px;font-weight:400;font-size:13px}
code{background:#0b0d11;padding:1px 4px;border-radius:4px}
</style></head><body>
<h1>__NAME__</h1><div id="sub">Your desktop spider, from your phone</div>
<div id="pair" class="card" hidden>
<p style="margin-top:0">Enter the 6-digit code shown on your laptop (right-click the spider → Phone link).</p>
<form id="pf"><input id="code" inputmode="numeric" maxlength="6" placeholder="123456" autocomplete="one-time-code"><button>Pair</button></form>
<p id="perr" style="color:#ff8a8a"></p></div>
<div id="chat" hidden>
<div class="chips"><button data-q="summary">Today</button><button data-q="reminders">Reminders</button><button data-a="tests">Run tests</button></div>
<div id="log"></div>
<form id="qf"><input id="q" placeholder="Ask, or: note: …  /  remind me in 20 min to …" autocomplete="off"><button>Send</button></form>
</div>
<script>
const $=s=>document.querySelector(s);
function esc(t){return t.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function md(t){return esc(t).replace(/\\*\\*(.+?)\\*\\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>')}
function add(cls,html){const d=document.createElement('div');d.className=cls;d.innerHTML=html;$('#log').appendChild(d);d.scrollIntoView({block:'end'});return d}
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined,credentials:'same-origin'});return [r.status,await r.json()]}
async function boot(){const [s,j]=await api('/api/status');if(j.paired){$('#chat').hidden=false;$('#pair').hidden=true;
$('#sub').textContent=(j.project?'Watching '+j.project+' · ':'')+'tests: '+j.tests}else{$('#pair').hidden=false;$('#chat').hidden=true}}
$('#pf').onsubmit=async e=>{e.preventDefault();const [s,j]=await api('/api/pair',{code:$('#code').value,name:navigator.userAgent.includes('iPhone')?'iPhone':'phone'});
if(s===200)boot();else $('#perr').textContent=j.error||'Try again.'};
async function ask(q){add('me',esc(q));const t=add('it','…');const [s,j]=await api('/api/ask',{q});t.innerHTML=md(j.text||j.error||'')}
$('#qf').onsubmit=e=>{e.preventDefault();const q=$('#q').value.trim();if(!q)return;$('#q').value='';ask(q)};
document.querySelectorAll('.chips button').forEach(b=>b.onclick=async()=>{if(b.dataset.q)return ask(b.dataset.q);
const [s,j]=await api('/api/tests',{});add('it',esc(j.text||''))});
boot();
</script></body></html>"""
