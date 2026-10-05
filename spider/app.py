"""The spider window: lives in a screen corner, draws the persona, and wires legs, bubble and the model together.

Routes (from Prompt Spider):  code → legs (free, instant) · model (OpenAI or Claude) → questions and fixes · you → approvals.
White core: nothing in your project is changed unless you press Approve.
"""
import os
import random
import sys
import time

from PyQt5.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QPainter
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QFileDialog, QMenu, QSystemTrayIcon, QWidget)

from . import settings as cfg
from .brain import Ask, apply_edit, build_context
from .bubble import Bubble
from .chat import ChatWindow
from .legs import Legs
from .memory import Memory, Stats, explicit_request, looks_secret
from .memory_panel import MemoryPanel
from .personas import PERSONAS, SpiderState
from . import always, sync, tasks
from .phone import PhoneLink

DRAW = 200                     # personas draw on a 200×200 canvas; the window scales it
SIZES = {"small": 130, "medium": 165, "large": 200}
FADE_AFTER = 20                # seconds of quiet before the spider fades
FADED = 0.35
CORNERS = {"top-left": (-1, -1), "top-right": (1, -1), "bottom-left": (-1, 1), "bottom-right": (1, 1)}


class SpiderWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.s = cfg.load()
        self.setFixedSize(self.px, self.px)
        self.setToolTip("Click to talk · right-click for options · drag to another corner")
        self.opacity = 1.0
        self.last_active = time.time()
        self.hovered = False
        self.st = SpiderState()
        self.st.focus = bool(self.s.get("focus"))
        self.t0 = time.time()
        self.drag_from = None
        self.history = []
        self.pending_edits = []
        self.worker = None
        self.long_notes = 0
        self.last_idle_line = time.time()
        self.seen_no_tests = False

        self.bubble = Bubble()
        self.bubble.clicked.connect(self.summon)
        self.chat = ChatWindow()
        self.chat.asked.connect(self.ask)
        self.chat.approved.connect(self.approve)
        self.chat.rejected.connect(self.reject)
        self.chat.stop_requested.connect(self.stop_answer)
        self.chat.cleared.connect(self.new_chat)
        self.chat.closed.connect(self._remember_chat_place)
        self.chat.restore(self.s.get("chat_geometry"))

        # memory: what the spider knows about you (each item approved by you)
        self.memory = Memory()
        self.stats = Stats()
        self.mem_queue = []          # [(fact, source)] waiting for your yes/no
        self.chat.mem_yes.connect(self.memory_yes)
        self.chat.mem_no.connect(self.memory_no)
        self.panel = MemoryPanel(self.memory)
        self.panel.learning_toggled.connect(lambda on: self._set("learning", on))
        self._restyle()

        self.legs = Legs(self.s, self)
        self.legs.leg_changed.connect(self.on_leg)
        self.legs.file_saved.connect(self.on_file_saved)
        self.legs.start()

        # stage 2: tasks
        self.reminders = tasks.Reminders()
        self.notes_path = tasks.NOTES_PATH
        self.remind_timer = QTimer(self)
        self.remind_timer.timeout.connect(self.check_reminders)
        self.remind_timer.start(15_000)

        # stage 3: where you left off
        self.session = always.load_session()
        self.history = list(self.session.get("history", []))[-8:]
        self.chat.load_history(self.history)

        # stage 3: tray icon
        self.tray = None
        if self.s.get("tray", True) and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self)
            self.tray.setToolTip("Desktop Spider")
            self._refresh_tray()
            self.tray.activated.connect(self._tray_clicked)
            self.tray.show()

        # stage 4: devices
        self.phone = PhoneLink(self, port=int(self.s.get("phone_port", 8765)))
        self.phone.offer.connect(lambda f: self.offer(f, source="told"))
        self.phone.run_tests.connect(self.legs.run_tests)
        self.phone.notify.connect(self.tell)
        if self.s.get("phone_link"):
            QTimer.singleShot(1500, lambda: self.set_phone_link(True, quiet=True))
        self.panel.changed.connect(self.sync_memory)
        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(lambda: self.sync_memory(quiet=True))
        self.sync_timer.start(5 * 60_000)
        QTimer.singleShot(2000, lambda: self.sync_memory(quiet=True))

        self.anim = QTimer(self)
        self.anim.timeout.connect(self.tick)
        self.anim.start(33)
        self.minute = QTimer(self)
        self.minute.timeout.connect(self.every_minute)
        self.minute.start(60_000)

        self.snap(self.s.get("corner", "bottom-right"))
        QTimer.singleShot(900, self.greet)

    # ── helpers
    @property
    def persona(self):
        return PERSONAS.get(self.s.get("persona"), PERSONAS["zip"])

    @property
    def px(self):
        return SIZES.get(self.s.get("size"), SIZES["small"])

    @property
    def corner(self):
        return CORNERS.get(self.s.get("corner"), (1, 1))

    def now(self):
        return time.time() - self.t0

    def set_mode(self, mode):
        if self.st.mode != mode:
            self.st.mode = mode
            self.st.mode_since = self.now()

    def speak(self, event, important=False, **kw):
        """Say a persona line, respecting chattiness and focus mode."""
        quiet = self.s.get("chattiness") == "silent" or self.st.focus
        if quiet and not important:
            return
        line = self.persona.say(event, **kw)
        if line:
            self.poke()
            self.bubble.say(line)

    def tell(self, line, ms=6000):
        """A notice: into the chat when it's open, otherwise a speech bubble."""
        self.poke()
        if self.chat.isVisible():
            self.chat.show_answer(line)
        else:
            self.bubble.say(line, ms)

    def poke(self):
        """Something happened: wake up from the idle fade."""
        self.last_active = time.time()

    def _restyle(self):
        self.bubble.style_for(self.persona.key, self.persona.name, self.s.get("accent", "#f2a93b"))
        label = cfg.PROVIDERS[cfg.provider(self.s)][1]
        self.chat.style_for(self.persona.key, self.persona.name, self.s.get("accent", "#f2a93b"),
                            f"{label} · {cfg.model_for(self.s)}")
        if hasattr(self, "panel"):
            self.panel.style_for(self.persona.key, self.persona.name, self.s.get("accent", "#f2a93b"), label)
        if getattr(self, "tray", None):
            self._refresh_tray()

    def save(self):
        cfg.save(self.s)

    # ── placement
    def snap(self, corner_name):
        self.s["corner"] = corner_name
        geo = QApplication.primaryScreen().availableGeometry()
        sx, sy = CORNERS[corner_name]
        x = geo.right() - self.px + 1 if sx > 0 else geo.left()
        y = geo.bottom() - self.px + 1 if sy > 0 else geo.top()
        self.move(x, y)
        self.bubble.place(self.frameGeometry(), self.corner)
        self.save()

    def nearest_corner(self):
        geo = QApplication.primaryScreen().availableGeometry()
        c = self.frameGeometry().center()
        h = "right" if c.x() > geo.center().x() else "left"
        v = "bottom" if c.y() > geo.center().y() else "top"
        return f"{v}-{h}"

    # ── drawing
    def tick(self):
        if self.st.mode == "pass" and self.now() - self.st.mode_since > 2.6:
            self.set_mode("idle")
        if self.s.get("chattiness") == "talkative" and self.st.mode == "idle" \
                and time.time() - self.last_idle_line > 480 and not self.bubble.isVisible() \
                and not self.chat.isVisible():
            self.last_idle_line = time.time()
            self.speak("idle")
        # fade when nothing is going on, so it never sits heavily over your work
        busy = (self.hovered or self.chat.isVisible() or self.bubble.isVisible() or self.drag_from is not None
                or self.st.mode not in ("idle", "pass") or self.st.legs.get("tests") == "fail")
        if busy:
            self.last_active = time.time()
        quiet = self.s.get("fade_when_idle", True) and time.time() - self.last_active > FADE_AFTER
        target = FADED if quiet else 1.0
        self.opacity += (target - self.opacity) * (0.04 if quiet else 0.35)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self.opacity)))
        p.scale(self.width() / DRAW, self.height() / DRAW)
        self.persona.draw(p, DRAW, DRAW, self.st, self.now(), self.corner, self.s.get("accent", "#f2a93b"))
        p.end()

    def enterEvent(self, e):
        self.hovered = True
        self.poke()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hovered = False
        self.poke()
        super().leaveEvent(e)

    # ── mouse
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag_from = e.globalPos()
            self.win_from = self.pos()

    def mouseMoveEvent(self, e):
        if self.drag_from is not None and e.buttons() & Qt.LeftButton:
            self.move(self.win_from + e.globalPos() - self.drag_from)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self.drag_from is None:
            return
        moved = (e.globalPos() - self.drag_from).manhattanLength()
        self.drag_from = None
        if moved > 6:
            self.snap(self.nearest_corner())
        else:
            self.toggle_chat()

    def contextMenuEvent(self, e):
        self.build_menu().exec_(e.globalPos())

    def build_menu(self):
        m = QMenu(self)
        m.addAction("Talk to me", self.summon)
        m.addAction("Today's summary", self.show_summary)
        m.addAction("Read a paper (PDF)…", self.read_paper)
        m.addAction("Open notes", self.open_notes)
        m.addAction(f"Memory ({len(self.memory.items)})…", self.open_memory)
        m.addSeparator()
        pm = m.addMenu("Persona")
        grp = QActionGroup(pm)
        for key, per in PERSONAS.items():
            a = QAction(per.name, pm, checkable=True, checked=(key == self.persona.key))
            a.triggered.connect(lambda _, k=key: self.switch_persona(k))
            grp.addAction(a)
            pm.addAction(a)
        cm = m.addMenu("Chattiness")
        grp2 = QActionGroup(cm)
        for level in ("silent", "normal", "talkative"):
            a = QAction(level.capitalize(), cm, checkable=True, checked=(self.s.get("chattiness") == level))
            a.triggered.connect(lambda _, l=level: self._set("chattiness", l))
            grp2.addAction(a)
            cm.addAction(a)
        bm = m.addMenu("Brain")
        grp3 = QActionGroup(bm)
        for prov, (_, label) in cfg.PROVIDERS.items():
            a = QAction(f"{label}  ({self.s.get(prov + '_model')})", bm, checkable=True,
                        checked=(cfg.provider(self.s) == prov))
            a.triggered.connect(lambda _, p=prov: self.set_provider(p))
            grp3.addAction(a)
            bm.addAction(a)
        zm = m.addMenu("Size")
        grp4 = QActionGroup(zm)
        for name in SIZES:
            a = QAction(name.capitalize(), zm, checkable=True, checked=(self.s.get("size", "small") == name))
            a.triggered.connect(lambda _, n=name: self.set_size(n))
            grp4.addAction(a)
            zm.addAction(a)
        zm.addSeparator()
        fd = QAction("Fade when idle", zm, checkable=True, checked=bool(self.s.get("fade_when_idle", True)))
        fd.triggered.connect(lambda on: (self._set("fade_when_idle", on), self.poke()))
        zm.addAction(fd)
        f = QAction("Focus mode", m, checkable=True, checked=self.st.focus)
        f.triggered.connect(self.toggle_focus)
        m.addAction(f)
        m.addSeparator()
        folder = self.s.get("watch_folder") or "none"
        m.addAction(f"Watching: {os.path.basename(folder) or folder}").setEnabled(False)
        m.addAction("Choose project folder…", self.choose_folder)
        m.addAction("Run tests now", self.legs.run_tests)
        m.addSeparator()
        am = m.addMenu("Always there")
        sw = QAction("Start with Windows", am, checkable=True, checked=always.startup_enabled())
        sw.setEnabled(bool(always.startup_dir()))
        sw.triggered.connect(self.toggle_startup)
        am.addAction(sw)
        hk = getattr(self, "hotkey", None)
        if hk and hk.ok:
            am.addAction(f"Shortcut: {hk.label}  (change \"hotkey\" in settings)").setEnabled(False)
        elif hk and hk.taken:
            am.addAction("Shortcut: none free (" + ", ".join(hk.taken) + " are taken)").setEnabled(False)
        am.addAction(f"Hide spider (the tray icon{' or ' + hk.label if hk and hk.ok else ''} brings it back)"
                     if self.isVisible() else "Show spider",
                     self.toggle_visible).setEnabled(bool(self.tray) or not self.isVisible())
        dm = m.addMenu("Devices")
        sf = self.s.get("sync_folder", "")
        if sf:
            dm.addAction(f"Memory syncs via: {os.path.basename(os.path.normpath(sf)) or sf}").setEnabled(False)
            dm.addAction("Sync memory now", self.sync_memory)
            dm.addAction("Stop syncing memory", self.stop_sync)
        else:
            dm.addAction("Sync memory through a folder…", self.choose_sync_folder)
        dm.addSeparator()
        pl = QAction("Phone link (local Wi-Fi)", dm, checkable=True, checked=self.phone.running)
        pl.triggered.connect(lambda on: self.set_phone_link(on))
        dm.addAction(pl)
        if self.phone.running:
            dm.addAction("Show pairing code", self.show_pairing)
        dm.addAction(f"Unpair all phones ({len(self.phone.devices)})", self.phone.unpair_all).setEnabled(bool(self.phone.devices))
        m.addSeparator()
        m.addAction("Open settings file", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(cfg.SETTINGS_PATH)))
        m.addAction("Quit", QApplication.quit)
        return m

    def _set(self, k, v):
        self.s[k] = v
        self.save()

    def set_size(self, name):
        self.s["size"] = name
        self.setFixedSize(self.px, self.px)
        self.snap(self.s.get("corner", "bottom-right"))
        self.poke()

    def switch_persona(self, key):
        self.s["persona"] = key
        self.save()
        self._restyle()
        self.bubble.close_bubble()
        self.t0 = time.time()        # replay the entrance
        self.speak("welcome", important=True)

    def toggle_focus(self):
        self.st.focus = not self.st.focus
        self.s["focus"] = self.st.focus
        self.save()
        if self.st.focus:
            self.bubble.close_bubble()

    def choose_folder(self):
        start = self.s.get("watch_folder") or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(None, "Which project should I watch?", start)
        if folder:
            self.s["watch_folder"] = folder
            recent = [f for f in self.s.get("recent_folders", []) if f != folder]
            self.s["recent_folders"] = ([folder] + recent)[:6]
            self.save()
            self.legs.start()
            self.speak("welcome", important=True)
            self.legs.run_tests()

    # ── greeting and timers
    def greet(self):
        last = self.session.get("last_seen", 0)
        folder = self.s.get("watch_folder")
        if folder and last and time.time() - last > 3 * 3600:
            self.speak("welcome_back", important=True, project=os.path.basename(os.path.normpath(folder)))
            return
        if not self.s.get("watch_folder"):
            self.speak("no_folder", important=True)
        else:
            self.speak("welcome", important=True)

    # ── memory
    def open_memory(self):
        self._restyle()
        self.panel.set_learning(bool(self.s.get("learning", True)))
        self.panel.refresh()
        geo = QApplication.primaryScreen().availableGeometry()
        sx, sy = self.corner
        x = self.x() - self.panel.width() - 10 if sx > 0 else self.x() + self.width() + 10
        y = geo.bottom() - self.panel.height() - 40 if sy > 0 else geo.top() + 40
        self.panel.move(max(geo.left(), x), max(geo.top(), y))
        self.panel.show()
        self.panel.raise_()
        self.panel.activateWindow()

    def on_file_saved(self, _path):
        if self.s.get("learning", True):
            self.stats.record_save(self.legs.folder)

    def offer(self, fact, source="told"):
        """Queue a fact; you decide in the bubble whether it's kept."""
        if not fact or self.memory.has(fact) or any(f == fact for f, _ in self.mem_queue):
            return
        self.mem_queue.append((fact, source))
        if not self.chat.mem_fact:
            self._next_offer()

    def _next_offer(self):
        if not self.mem_queue:
            self.chat.clear_memory_offer()
            return
        fact, source = self.mem_queue[0]
        line = self.persona.say("noticed_offer" if source == "noticed" else "remember_offer")
        self.chat.offer_memory(line, fact)
        self.chat.open_chat()

    def _settle_offer(self, line):
        self.mem_queue = self.mem_queue[1:]
        self.chat.settle_memory(line)

        def done():
            self._next_offer()
        QTimer.singleShot(1300, done)

    def memory_yes(self, fact):
        source = self.mem_queue[0][1] if self.mem_queue else "told"
        ok, why = self.memory.add(fact, source=source)
        line = self.persona.say("remembered") if ok else self.persona.say(
            {"secret": "secret_refused", "duplicate": "already_known"}.get(why, "not_now"))
        if self.panel.isVisible():
            self.panel.refresh()
        if ok:
            self.sync_memory(quiet=True)
        self._settle_offer(line)

    def memory_no(self, _fact):
        self._settle_offer(self.persona.say("not_now"))

    # ── stage 2: tasks
    def run_command(self, kind, payload):
        if kind == "note":
            tasks.add_note(payload, self.notes_path)
            self.chat.show_answer(f"{self.persona.say('noted')}\n\n*{payload}*")
        elif kind == "remind":
            r = self.reminders.add(payload["at"], payload["text"])
            self.chat.show_answer(self.persona.say("reminder_set", when=tasks.when_text(r["at"]), text=r["text"]))
        elif kind == "list_reminders":
            ups = self.reminders.upcoming()
            self.chat.show_answer("\n".join(f"- {tasks.when_text(r['at'])}: {r['text']}" for r in ups)
                                  or "No reminders set.")
        elif kind == "summary":
            self.chat.show_answer(self.summary_text())

    def summary_text(self):
        folders = [f for f in dict.fromkeys([self.s.get("watch_folder", "")] + self.s.get("recent_folders", [])) if f]
        return tasks.daily_summary(folders, self.stats.saves_today(), self.reminders.upcoming(),
                                   tasks.recent_notes(3, self.notes_path))

    def show_summary(self):
        self.chat.add_user("Today's summary")
        self.chat.show_answer(self.summary_text())

    def check_reminders(self):
        for r in self.reminders.due():
            self.tell(self.persona.say("reminder", text=r["text"]), 30_000)
            if self.tray:
                self.tray.showMessage(self.persona.name, r["text"], QSystemTrayIcon.Information, 15_000)

    def open_notes(self):
        if not os.path.exists(self.notes_path):
            tasks.add_note("Notes start here. Type 'note: …' to the spider to add one.", self.notes_path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.notes_path))

    def read_paper(self):
        path, _ = QFileDialog.getOpenFileName(None, "Which paper should I read?", os.path.expanduser("~"),
                                              "PDF files (*.pdf)")
        if not path:
            return
        text, err = tasks.pdf_text(path)
        self.chat.open_chat()
        if err:
            self.chat.show_answer(err)
            return
        ctx = f"Paper: {os.path.basename(path)}\n\n{text}"
        self.ask(tasks.PAPER_QUESTION, extra_context=ctx, shown=f"Read the paper {os.path.basename(path)}")

    # ── stage 3: always there
    def summon(self):
        if not self.isVisible():
            self.show()
        self.raise_()
        self.poke()
        self.open_chat()

    def toggle_visible(self):
        if self.isVisible():
            self.hide()
            self.bubble.close_bubble()
            self.chat.close_chat()
        else:
            self.show()

    def toggle_startup(self, on):
        ok, msg = always.set_startup(on)
        self.tell(("I'll be here when Windows starts." if on else "I won't start with Windows.")
                  if ok else f"Couldn't change that: {msg}")

    def _refresh_tray(self):
        self.tray.setIcon(always.persona_icon(self.persona, SpiderState(), self.s.get("accent", "#f2a93b")))
        self.tray.setContextMenu(None)

    def _tray_clicked(self, reason):
        if reason == QSystemTrayIcon.Context:
            self.build_menu().exec_(self.cursor().pos())
        elif reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.summon()

    def _remember_chat_place(self):
        self.s["chat_geometry"] = self.chat.geom()
        self.save()

    def shutdown(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)
        if self.chat.isVisible():
            self._remember_chat_place()
        always.save_session(self.history, self.legs.folder)
        self.phone.stop()
        self.sync_memory(quiet=True)
        if self.tray:
            self.tray.hide()

    # ── stage 4: devices
    def choose_sync_folder(self):
        folder = QFileDialog.getExistingDirectory(
            None, "Pick a folder your cloud drive syncs (e.g. OneDrive). Memory will be shared through it.",
            os.path.expanduser("~"))
        if folder:
            self.s["sync_folder"] = folder
            self.save()
            self.sync_memory()

    def stop_sync(self):
        self.s["sync_folder"] = ""
        self.save()
        self.tell("Memory stays on this device now.")

    def sync_memory(self, quiet=False):
        folder = self.s.get("sync_folder", "")
        if not folder:
            return
        ok, msg, changed = sync.sync(self.memory, folder)
        if changed and self.panel.isVisible():
            self.panel.refresh()
        if not quiet:
            self.tell(self.persona.say("synced") if ok else msg)

    def set_phone_link(self, on, quiet=False):
        if on:
            ok, info = self.phone.start()
            self.s["phone_link"] = ok
            self.save()
            if not ok:
                self.tell(info, 10_000)
            elif not quiet:
                self.show_pairing()
        else:
            self.phone.stop()
            self.s["phone_link"] = False
            self.save()
            self.tell("Phone link is off.")

    def show_pairing(self):
        code = self.phone.current_code()
        self.chat.show_answer(
            f"{self.persona.say('phone_on')}\n\nOn your phone, connected to the same Wi-Fi, open:\n\n"
            f"**{self.phone.url()}**\n\nPairing code: **{code[:3]} {code[3:]}** (works once, for 10 minutes)\n\n"
            "If Windows asks whether Python may use the network, allow it on **private** networks only.")

    def every_minute(self):
        hours = max(1, int(self.s.get("long_session_hours", 3)))
        elapsed_h = (time.time() - self.t0) / 3600
        if elapsed_h >= hours * (self.long_notes + 1):
            self.long_notes += 1
            self.speak("long_session", hours=hours * self.long_notes)
        if self.s.get("learning", True) and not self.st.focus and self.st.mode == "idle" \
                and not self.bubble.isVisible() and not self.chat.isVisible():
            noticed = self.stats.suggestion(self.memory)
            if noticed:
                self.offer(noticed, source="noticed")

    # ── code route: legs
    def on_leg(self, leg, state, info):
        self.st.legs[leg] = state
        if self.st.mode in ("thinking", "waiting"):
            return      # don't interrupt the model or a pending approval
        if leg == "syntax" and state == "fail":
            self.set_mode("fail")
            self.speak("syntax", file=info["file"], line=info["line"])
        elif leg == "tests":
            if state == "running":
                self.set_mode("running")
            elif state == "pass":
                self.set_mode("pass")
                cx, cy = DRAW * 0.5, DRAW * 0.5
                self.st.splats = [(cx + random.uniform(-60, 60), cy + random.uniform(-60, 60),
                                   random.uniform(4, 9), self.now()) for _ in range(3)]
                self.speak("pass", n=info.get("passed", 0))
            elif state == "fail":
                self.set_mode("fail")
                if info.get("line"):
                    self.speak("fail", test=info["test"], line=info["line"])
                else:
                    self.speak("fail_noline", test=info["test"])
            elif state == "none":
                self.set_mode("idle")
                if not self.seen_no_tests:
                    self.seen_no_tests = True
                    self.speak("no_tests")

    # ── model route
    def toggle_chat(self):
        if self.chat.mode == "chat":
            self.chat.close_chat()
        else:
            self.open_chat()

    def open_chat(self):
        self.chat.place_near(self.frameGeometry(), self.corner)
        intro = "" if cfg.api_key(cfg.provider(self.s)) else self._no_key_line()
        self.bubble.close_bubble()
        self.chat.open_chat(intro)

    def ask(self, question, extra_context=None, shown=None):
        self.poke()
        if self.worker and self.worker.isRunning():
            return
        self.chat.add_user(shown or question)
        cmd = None if extra_context else tasks.parse_command(question)
        if cmd:
            self.run_command(*cmd)
            return
        fact = explicit_request(question)
        if fact:                     # "remember that …" is handled locally, no model call
            if looks_secret(fact):
                self.chat.show_answer(self.persona.say("secret_refused"))
            else:
                self.chat.show_answer(f"*{fact}*")
                self.offer(fact, source="told")
            return
        prov = cfg.provider(self.s)
        key = cfg.api_key(prov)
        if not key:
            self.chat.show_answer(self._no_key_line())
            return
        self.set_mode("thinking")
        self.chat.begin_answer(self.persona.say("thinking"))
        ctx = extra_context or build_context(self.legs.folder, self.legs.last_file, self.legs.last_output,
                                             self.legs.last_syntax)
        self._learned = []
        self.worker = Ask(prov, key, cfg.model_for(self.s), self.persona.voice, self.history, question, ctx,
                          self.legs.folder, memory_text=self.memory.as_prompt())
        self.worker.partial.connect(self.chat.stream)
        self.worker.activity.connect(self.chat.show_activity)
        self.worker.learned.connect(self.on_learned)
        self.worker.answered.connect(lambda text, edits, q=question: self.on_answer(q, text, edits))
        self.worker.failed.connect(self.on_fail)
        self.worker.start()

    def stop_answer(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()

    def new_chat(self):
        self.history = []
        always.save_session(self.history, self.legs.folder)

    def _no_key_line(self):
        var, label = cfg.PROVIDERS[cfg.provider(self.s)]
        return self.persona.say("no_key", var=var, provider=label)

    def set_provider(self, prov):
        self.s["provider"] = prov
        self.save()
        self.history = []
        self._restyle()
        self.tell(f"{cfg.PROVIDERS[prov][1]} · {cfg.model_for(self.s)}", 3500)

    def on_learned(self, facts):
        self._learned = [] if not self.s.get("learning", True) else facts

    def on_answer(self, question, text, edits):
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": text}]
        self.history = self.history[-12:]
        always.save_session(self.history, self.legs.folder)
        self.chat.finish_answer(text)
        if edits:
            self.pending_edits = list(edits)
            self.set_mode("waiting")     # the "you" route: gold thread, nothing written yet
            self.chat.show_edits(self.persona.say("needs_approval"), self.pending_edits)
        else:
            self.set_mode("idle")
        for fact in getattr(self, "_learned", []):
            self.offer(fact, source="told")
        self._learned = []

    def on_fail(self, msg):
        self.set_mode("idle")
        self.chat.finish_answer(self.persona.say("error", msg=msg))

    # ── you route
    def approve(self):
        edits, self.pending_edits = self.pending_edits, []
        self.chat.clear_edits()
        if not edits:
            return
        done, errors = [], []
        for e in edits:
            try:
                apply_edit(self.legs.folder, e["target"], e["text"])
                done.append(e["rel"])
            except OSError as err:
                errors.append(f"{e['rel']}: {err}")
        self.set_mode("idle")
        lines = [self.persona.say("approved") if done else self.persona.say("error", msg="; ".join(errors))]
        if done:
            lines.append("Written: " + ", ".join(f"`{r}`" for r in done) + " (old copies in `.spider_backups/`).")
        if done and errors:
            lines.append("Not written: " + "; ".join(errors))
        self.chat.show_answer("\n\n".join(lines))
        if done:
            self.legs.run_tests()

    def reject(self):
        self.pending_edits = []
        self.chat.clear_edits()
        self.set_mode("idle")
        self.chat.show_answer(self.persona.say("rejected"))

    def moveEvent(self, e):
        self.bubble.place(self.frameGeometry(), self.corner)
        super().moveEvent(e)


def main():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lock = always.single_instance()
    if lock is None:            # a spider is already running; don't start a second one
        sys.exit(0)
    w = SpiderWindow()
    w.show()
    hotkey = always.Hotkey(app, w.s.get("hotkey", "ctrl+alt+v"))
    hotkey.pressed.connect(w.summon)
    w.hotkey = hotkey
    if hotkey.ok and hotkey.taken:
        QTimer.singleShot(2500, lambda: w.tell(f"{', '.join(hotkey.taken)} belongs to another app, "
                                               f"so my shortcut is {hotkey.label}."))
    app.aboutToQuit.connect(w.shutdown)
    app.aboutToQuit.connect(hotkey.release)
    code = app.exec_()
    lock.unlock()
    sys.exit(code)
