"""The spider window: lives in a screen corner, draws the persona, and wires legs, bubble and Claude together.

Routes (from Prompt Spider):  code → legs (free, instant) · claude → questions and fixes · you → approvals.
White core: nothing in your project is changed unless you press Approve.
"""
import os
import random
import sys
import time

from PyQt5.QtCore import QPoint, QRect, Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QPainter
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QFileDialog, QMenu, QWidget)

from . import settings as cfg
from .brain import Ask, apply_edit, build_context
from .bubble import Bubble
from .legs import Legs
from .personas import PERSONAS, SpiderState

SIZE = 200
CORNERS = {"top-left": (-1, -1), "top-right": (1, -1), "bottom-left": (-1, 1), "bottom-right": (1, 1)}


class SpiderWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(SIZE, SIZE)
        self.setToolTip("Click to talk · right-click for options · drag to another corner")
        self.s = cfg.load()
        self.st = SpiderState()
        self.st.focus = bool(self.s.get("focus"))
        self.t0 = time.time()
        self.drag_from = None
        self.history = []
        self.pending_edit = None
        self.worker = None
        self.long_notes = 0
        self.last_idle_line = time.time()
        self.seen_no_tests = False

        self.bubble = Bubble()
        self.bubble.asked.connect(self.ask)
        self.bubble.approved.connect(self.approve)
        self.bubble.rejected.connect(self.reject)
        self._restyle()

        self.legs = Legs(self.s, self)
        self.legs.leg_changed.connect(self.on_leg)
        self.legs.start()

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
        return PERSONAS.get(self.s.get("persona"), PERSONAS["vesper"])

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
            self.bubble.say(line)

    def _restyle(self):
        self.bubble.style_for(self.persona.key, self.persona.name, self.s.get("accent", "#f2a93b"))

    def save(self):
        cfg.save(self.s)

    # ── placement
    def snap(self, corner_name):
        self.s["corner"] = corner_name
        geo = QApplication.primaryScreen().availableGeometry()
        sx, sy = CORNERS[corner_name]
        x = geo.right() - SIZE + 1 if sx > 0 else geo.left()
        y = geo.bottom() - SIZE + 1 if sy > 0 else geo.top()
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
                and time.time() - self.last_idle_line > 480 and not self.bubble.isVisible():
            self.last_idle_line = time.time()
            self.speak("idle")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.persona.draw(p, self.width(), self.height(), self.st, self.now(), self.corner,
                          self.s.get("accent", "#f2a93b"))
        p.end()

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
        m = QMenu(self)
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
        f = QAction("Focus mode", m, checkable=True, checked=self.st.focus)
        f.triggered.connect(self.toggle_focus)
        m.addAction(f)
        m.addSeparator()
        folder = self.s.get("watch_folder") or "none"
        m.addAction(f"Watching: {os.path.basename(folder) or folder}").setEnabled(False)
        m.addAction("Choose project folder…", self.choose_folder)
        m.addAction("Run tests now", self.legs.run_tests)
        m.addAction("Talk to me", self.toggle_chat)
        m.addSeparator()
        m.addAction("Open settings file", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(cfg.SETTINGS_PATH)))
        m.addAction("Quit", QApplication.quit)
        m.exec_(e.globalPos())

    def _set(self, k, v):
        self.s[k] = v
        self.save()

    def switch_persona(self, key):
        self.s["persona"] = key
        self.save()
        self._restyle()
        self.bubble.close_bubble()
        self.speak("welcome", important=True)

    def toggle_focus(self):
        self.st.focus = not self.st.focus
        self.s["focus"] = self.st.focus
        self.save()
        if self.st.focus and self.bubble.mode != "approve":
            self.bubble.close_bubble()

    def choose_folder(self):
        start = self.s.get("watch_folder") or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(None, "Which project should I watch?", start)
        if folder:
            self.s["watch_folder"] = folder
            self.save()
            self.legs.start()
            self.speak("welcome", important=True)
            self.legs.run_tests()

    # ── greeting and timers
    def greet(self):
        if not self.s.get("watch_folder"):
            self.speak("no_folder", important=True)
        else:
            self.speak("welcome", important=True)

    def every_minute(self):
        hours = max(1, int(self.s.get("long_session_hours", 3)))
        elapsed_h = (time.time() - self.t0) / 3600
        if elapsed_h >= hours * (self.long_notes + 1):
            self.long_notes += 1
            self.speak("long_session", hours=hours * self.long_notes)

    # ── code route: legs
    def on_leg(self, leg, state, info):
        self.st.legs[leg] = state
        if self.st.mode in ("thinking", "waiting"):
            return      # don't interrupt Claude or a pending approval
        if leg == "syntax" and state == "fail":
            self.set_mode("fail")
            self.speak("syntax", file=info["file"], line=info["line"])
        elif leg == "tests":
            if state == "running":
                self.set_mode("running")
            elif state == "pass":
                self.set_mode("pass")
                cx, cy = self.width() * 0.5, self.height() * 0.5
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

    # ── claude route
    def toggle_chat(self):
        if self.bubble.mode == "approve":
            self.bubble._show()
            return
        if self.bubble.mode == "chat":
            self.bubble.close_bubble()
            return
        intro = ""
        if not cfg.api_key():
            intro = self.persona.say("no_key")
        self.bubble.open_chat(intro)

    def ask(self, question):
        key = cfg.api_key()
        if not key:
            self.bubble.open_chat(self.persona.say("no_key"))
            return
        if self.worker and self.worker.isRunning():
            return
        self.set_mode("thinking")
        self.bubble.show_thinking(self.persona.say("thinking"))
        ctx = build_context(self.legs.folder, self.legs.last_file, self.legs.last_output, self.legs.last_syntax)
        self.worker = Ask(key, self.s.get("model"), self.persona.voice, self.history, question, ctx,
                          self.legs.folder)
        self.worker.answered.connect(lambda text, edit, q=question: self.on_answer(q, text, edit))
        self.worker.failed.connect(self.on_fail)
        self.worker.start()

    def on_answer(self, question, text, edit):
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": text}]
        self.history = self.history[-12:]
        if edit:
            self.pending_edit = edit
            self.set_mode("waiting")     # the "you" route: gold thread, nothing written yet
            self.bubble.show_edit(self.persona.say("needs_approval"), text, edit["diff"])
        else:
            self.set_mode("idle")
            self.bubble.show_answer(text)

    def on_fail(self, msg):
        self.set_mode("idle")
        self.bubble.show_answer(self.persona.say("error", msg=msg))

    # ── you route
    def approve(self):
        e, self.pending_edit = self.pending_edit, None
        if not e:
            return
        try:
            apply_edit(self.legs.folder, e["target"], e["text"])
        except OSError as err:
            self.set_mode("idle")
            self.bubble.show_answer(self.persona.say("error", msg=str(err)))
            return
        self.set_mode("idle")
        self.bubble.close_bubble()
        self.bubble.say(self.persona.say("approved"))
        self.legs.run_tests()

    def reject(self):
        self.pending_edit = None
        self.set_mode("idle")
        self.bubble.close_bubble()
        self.bubble.say(self.persona.say("rejected"))

    def moveEvent(self, e):
        self.bubble.place(self.frameGeometry(), self.corner)
        super().moveEvent(e)


def main():
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = SpiderWindow()
    w.show()
    sys.exit(app.exec_())
