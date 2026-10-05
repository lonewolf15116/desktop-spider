"""The chat window: history, streaming replies, code blocks with Copy, multi-file approvals and memory offers.

It's an ordinary resizable window that remembers where you put it. The little speech bubble next to the
spider is only for short lines now.
"""
import html
import re

from PyQt5.QtCore import QRect, QSize, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QFontDatabase, QGuiApplication
from .web import WebStrip
from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                             QScrollArea, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget)

FENCE = re.compile(r"```([^\n`]*)\n(.*?)(?:```|\Z)", re.S)
EDIT_DONE = re.compile(r"```edit\s+path=([^\s`]+)\s*\n.*?```", re.S)
EDIT_OPEN = re.compile(r"```edit\s+path=([^\s`]+)[^\n]*(?:\n.*)?\Z", re.S)
REMEMBER = re.compile(r"(?im)^\s*remember:.*$")


def display_text(raw):
    """What a reply looks like while it streams: edit blocks become one line, remember: lines are hidden."""
    t = EDIT_DONE.sub(lambda m: f"\n*✎ proposed changes to `{m.group(1)}`*\n", raw)
    t = EDIT_OPEN.sub(lambda m: f"\n*✎ writing changes to `{m.group(1)}`…*", t)
    return REMEMBER.sub("", t).strip()


def segments(md):
    """Split markdown into [("text", str) | ("code", lang, str)], tolerating an unclosed fence while streaming."""
    out, pos = [], 0
    for m in FENCE.finditer(md):
        if m.start() > pos and md[pos:m.start()].strip():
            out.append(("text", md[pos:m.start()].strip()))
        out.append(("code", m.group(1).strip(), m.group(2).rstrip("\n")))
        pos = m.end()
    if md[pos:].strip():
        out.append(("text", md[pos:].strip()))
    return out


STYLES = {
    "zip": dict(bg="#121519", card="#1b2027", user="#173b3a", text="#e7eef0", muted="#8796a0",
                accent="#22d3c5", warm="#ff8a3d", border="rgba(34,211,197,70)", code="#0b0d10",
                font='"Segoe UI", "Inter", sans-serif', yes_fg="#06211f"),
    "vesper": dict(bg="#0f1116", card="#181b22", user="#2a2416", text="#e9e4d8", muted="#8b929e",
                   accent="{accent}", warm="{accent}", border="rgba(255,255,255,40)", code="#0a0b0e",
                   font='"Segoe UI", sans-serif', yes_fg="#1b1505"),
    "nib": dict(bg="#fbf7ef", card="#ffffff", user="#fff3c4", text="#1a1a1a", muted="#6b6b6b",
                accent="#111111", warm="#f5c542", border="#111111", code="#f4f1ea",
                font='"Segoe Print", "Comic Sans MS", sans-serif', yes_fg="#111111"),
}

SHEET = """
QWidget#chat {{ background: {bg}; }}
QLabel {{ color: {text}; font-family: {font}; font-size: 10pt; background: transparent; }}
QLabel#name {{ color: {accent}; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }}
QLabel#model, QLabel#activity, QLabel#hint {{ color: {muted}; font-size: 8.5pt; }}
QScrollArea, QWidget#list {{ background: transparent; border: none; }}
QFrame#user {{ background: {user}; border-radius: 12px; }}
QFrame#bot {{ background: {card}; border: 1px solid {border}; border-radius: 12px; }}
QFrame#note {{ background: transparent; border: 1px dashed {border}; border-radius: 10px; }}
QFrame#code {{ background: {code}; border: 1px solid {border}; border-radius: 8px; }}
QLabel#lang {{ color: {muted}; font-size: 8pt; }}
QPlainTextEdit#codebody {{ background: transparent; color: {text}; border: none; font-family: Consolas, "Cascadia Mono", monospace; font-size: 9pt; }}
QPlainTextEdit#input {{ background: {card}; color: {text}; border: 1px solid {border}; border-radius: 10px;
                        padding: 6px; font-family: {font}; font-size: 10pt; }}
QPushButton {{ background: transparent; color: {text}; border: 1px solid {border}; border-radius: 8px;
               padding: 5px 12px; font-size: 9pt; }}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton#send, QPushButton#yes, QPushButton#memyes {{ background: {warm}; color: {yes_fg}; border: none; font-weight: 600; }}
QPushButton#copy {{ padding: 2px 8px; font-size: 8pt; }}
QPushButton#flat {{ border: none; color: {muted}; }}
QFrame#approve {{ background: {card}; border: 2px solid #f5c542; border-radius: 12px; }}
QFrame#memrow {{ background: rgba(245,197,66,30); border: 1px solid rgba(245,197,66,150); border-radius: 10px; }}
QTextBrowser#diff {{ background: {code}; color: {text}; border: 1px solid {border}; border-radius: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}
"""


def _diff_html(diff):
    rows = []
    for line in diff.splitlines():
        esc = html.escape(line) or "&nbsp;"
        if line.startswith("+") and not line.startswith("+++"):
            rows.append(f'<div style="background:rgba(79,211,138,0.20);color:#2fbf71">{esc}</div>')
        elif line.startswith("-") and not line.startswith("---"):
            rows.append(f'<div style="background:rgba(255,107,107,0.18);color:#e05252">{esc}</div>')
        elif line.startswith("@@"):
            rows.append(f'<div style="color:#5aa9ff">{esc}</div>')
        else:
            rows.append(f'<div style="color:#8a93a0">{esc}</div>')
    return '<pre style="font-family:Consolas,monospace;font-size:8.5pt;margin:0">' + "".join(rows) + "</pre>"


class CodeBlock(QFrame):
    def __init__(self, lang, code):
        super().__init__(objectName="code")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 4, 6, 6)
        lay.setSpacing(2)
        top = QHBoxLayout()
        self.lang = QLabel(objectName="lang")
        self.copy = QPushButton("Copy", objectName="copy")
        self.copy.setCursor(Qt.PointingHandCursor)
        self.copy.clicked.connect(self._copy)
        top.addWidget(self.lang)
        top.addStretch(1)
        top.addWidget(self.copy)
        lay.addLayout(top)
        self.body = QPlainTextEdit(objectName="codebody", readOnly=True)
        self.body.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.body.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.body.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        lay.addWidget(self.body)
        self.set_code(lang, code)

    def set_code(self, lang, code):
        self.lang.setText(lang or "code")
        if self.body.toPlainText() != code:
            self.body.setPlainText(code)
        lines = max(1, code.count("\n") + 1)
        lh = self.body.fontMetrics().lineSpacing()
        self.body.setFixedHeight(min(22 * lh, lines * lh + 14))

    def _copy(self):
        QGuiApplication.clipboard().setText(self.body.toPlainText())
        self.copy.setText("Copied")
        QTimer.singleShot(1200, lambda: self.copy.setText("Copy"))


class MdLabel(QLabel):
    """A word-wrapped label whose size hint matches its real height (QLabel's own guess is far too tall)."""

    def sizeHint(self):
        hint = super().sizeHint()
        w = self.width() if self.width() > 50 else 360
        return QSize(hint.width(), self.heightForWidth(w))

    def minimumSizeHint(self):
        return QSize(super().minimumSizeHint().width(), self.sizeHint().height())


def _text_label(md):
    lab = MdLabel(wordWrap=True)
    lab.setTextFormat(Qt.MarkdownText)
    lab.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
    lab.setOpenExternalLinks(True)
    lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    lab.setText(md)
    return lab


class Message(QFrame):
    """One chat turn. Assistant turns are re-rendered in place as the reply streams."""

    def __init__(self, role, md=""):
        super().__init__(objectName={"user": "user", "note": "note"}.get(role, "bot"))
        self.role = role
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 8, 12, 8)
        self.lay.setSpacing(6)
        self.parts = []          # [(kind, widget)]
        self.md = None
        self.set_markdown(md)

    def set_markdown(self, md):
        if md == self.md:
            return
        self.md = md
        segs = segments(md) if self.role != "user" else [("text", html.escape(md).replace("\n", "  \n"))]
        for i, seg in enumerate(segs):
            kind = seg[0]
            if i < len(self.parts) and self.parts[i][0] == kind:
                w = self.parts[i][1]
                if kind == "text":
                    if w.text() != seg[1]:
                        w.setText(seg[1])
                else:
                    w.set_code(seg[1], seg[2])
                continue
            for _, old in self.parts[i:]:          # shape changed from here on: rebuild the tail
                old.setParent(None)
                old.deleteLater()
            self.parts = self.parts[:i]
            w = _text_label(seg[1]) if kind == "text" else CodeBlock(seg[1], seg[2])
            self.lay.addWidget(w)
            self.parts.append((kind, w))
        for _, old in self.parts[len(segs):]:
            old.setParent(None)
            old.deleteLater()
        self.parts = self.parts[:len(segs)]


class Input(QPlainTextEdit):
    send = pyqtSignal()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
            self.send.emit()
            return
        super().keyPressEvent(e)


class ChatWindow(QWidget):
    asked = pyqtSignal(str)
    approved = pyqtSignal()
    rejected = pyqtSignal()
    mem_yes = pyqtSignal(str)
    mem_no = pyqtSignal(str)
    stop_requested = pyqtSignal()
    cleared = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setObjectName("chat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumSize(340, 360)
        self.resize(460, 600)
        self.busy = False
        self.current = None       # the assistant Message being streamed
        self._pending_md = None
        self.mem_fact = ""
        self.placed = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.name = QLabel(objectName="name")
        self.model = QLabel(objectName="model")
        self.newbtn = QPushButton("New chat", objectName="flat")
        self.newbtn.clicked.connect(self.clear)
        head.addWidget(self.name)
        head.addWidget(self.model)
        head.addStretch(1)
        head.addWidget(self.newbtn)
        lay.addLayout(head)
        self.web = WebStrip()          # one leg per thing pulled in for the current answer
        self.web.hide()
        lay.addWidget(self.web)

        self.scroll = QScrollArea(widgetResizable=True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list = QWidget(objectName="list")
        self.vbox = QVBoxLayout(self.list)
        self.vbox.setContentsMargins(0, 0, 4, 0)
        self.vbox.setSpacing(8)
        self.vbox.addStretch(1)
        self.scroll.setWidget(self.list)
        self.scroll.verticalScrollBar().rangeChanged.connect(self._stick_bottom)
        self.follow = True
        self.scroll.verticalScrollBar().valueChanged.connect(self._track_follow)
        lay.addWidget(self.scroll, 1)

        # the "you" route: proposed edits wait here for Approve
        self.approve_card = QFrame(objectName="approve")
        al = QVBoxLayout(self.approve_card)
        al.setContentsMargins(12, 10, 12, 10)
        al.setSpacing(6)
        self.approve_line = QLabel(wordWrap=True)
        self.diffs = QTextBrowser(objectName="diff")
        self.diffs.setLineWrapMode(QTextBrowser.NoWrap)
        self.diffs.setMinimumHeight(140)
        brow = QHBoxLayout()
        self.files_label = QLabel(objectName="hint")
        self.no = QPushButton("Reject")
        self.yes = QPushButton("Approve", objectName="yes")
        self.no.clicked.connect(self.rejected.emit)
        self.yes.clicked.connect(self.approved.emit)
        brow.addWidget(self.files_label)
        brow.addStretch(1)
        brow.addWidget(self.no)
        brow.addWidget(self.yes)
        al.addWidget(self.approve_line)
        al.addWidget(self.diffs, 1)
        al.addLayout(brow)
        self.approve_card.hide()
        lay.addWidget(self.approve_card, 1)

        # "Shall I keep this thread?"
        self.memrow = QFrame(objectName="memrow")
        ml = QHBoxLayout(self.memrow)
        ml.setContentsMargins(10, 6, 8, 6)
        self.memtext = QLabel(wordWrap=True)
        self.memyes = QPushButton("Remember", objectName="memyes")
        self.memno = QPushButton("Not now", objectName="flat")
        self.memyes.clicked.connect(lambda: self.mem_yes.emit(self.mem_fact))
        self.memno.clicked.connect(lambda: self.mem_no.emit(self.mem_fact))
        ml.addWidget(self.memtext, 1)
        ml.addWidget(self.memno)
        ml.addWidget(self.memyes)
        self.memrow.hide()
        lay.addWidget(self.memrow)

        self.activity = QLabel(objectName="activity")
        self.activity.hide()
        lay.addWidget(self.activity)
        row = QHBoxLayout()
        self.input = Input(objectName="input")
        self.input.setPlaceholderText("Ask about your code…  (Enter sends, Shift+Enter for a new line)")
        self.input.setFixedHeight(64)
        self.input.send.connect(self._submit)
        self.sendbtn = QPushButton("Send", objectName="send")
        self.sendbtn.clicked.connect(self._send_or_stop)
        row.addWidget(self.input, 1)
        row.addWidget(self.sendbtn, 0, Qt.AlignBottom)
        lay.addLayout(row)

        self.render_timer = QTimer(self, singleShot=True)
        self.render_timer.timeout.connect(self._render_pending)

    # ── look
    def style_for(self, key, persona_name, accent, model_label=""):
        pal = dict(STYLES.get(key, STYLES["zip"]))
        pal = {k: v.format(accent=accent) for k, v in pal.items()}
        self.setStyleSheet(SHEET.format(**pal))
        self.name.setText(persona_name.upper() if key == "vesper" else persona_name)
        self.model.setText(model_label)
        self.setWindowTitle(f"{persona_name} · Desktop Spider")
        self.web.style_for(key, accent)

    @property
    def mode(self):
        if not self.isVisible():
            return "hidden"
        return "approve" if self.approve_card.isVisible() else "chat"

    # ── messages
    def _add(self, msg):
        self.vbox.insertWidget(self.vbox.count() - 1, msg)
        self.follow = True
        return msg

    def add_user(self, text):
        return self._add(Message("user", text))

    def show_answer(self, md):
        """A complete message from the spider (notices, local commands, errors)."""
        self.open_chat()
        return self._add(Message("bot", md))

    def note(self, md):
        return self._add(Message("note", md))

    def load_history(self, history):
        for m in history[-8:]:
            if m.get("role") == "user":
                self.add_user(m.get("content", ""))
            elif m.get("role") == "assistant":
                self._add(Message("bot", display_text(m.get("content", ""))))

    def clear(self):
        if self.busy:
            return
        while self.vbox.count() > 1:
            w = self.vbox.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.web.reset()
        self.web.hide()
        self.cleared.emit()

    # ── streaming
    def begin_answer(self, thinking_line):
        self.set_busy(True)
        self.web.reset()
        self.web.show()
        self.current = self._add(Message("bot", f"*{thinking_line}*"))
        self.show_activity("")

    def stream(self, raw):
        """Called with the whole reply so far; re-rendered at most ~12 times a second."""
        if self.current is None:
            return
        self._pending_md = display_text(raw)
        if self.activity.isVisible():
            self.show_activity("")
        if not self.render_timer.isActive():
            self.render_timer.start(80)

    def _render_pending(self):
        if self.current is not None and self._pending_md is not None:
            self.current.set_markdown(self._pending_md or "…")
        self._pending_md = None

    def show_activity(self, line):
        self.activity.setText(f"🕸  {line}" if line else "")
        self.activity.setVisible(bool(line))

    def finish_answer(self, md):
        self.render_timer.stop()
        self._pending_md = None
        if self.current is not None:
            self.current.set_markdown(md)
        else:
            self._add(Message("bot", md))
        self.current = None
        self.set_busy(False)

    def set_busy(self, on):
        self.busy = on
        self.sendbtn.setText("Stop" if on else "Send")
        self.newbtn.setEnabled(not on)
        if not on:
            self.show_activity("")

    # ── the "you" route
    def show_edits(self, line, edits):
        self.open_chat()
        self.approve_line.setText(line)
        parts = []
        for e in edits:
            parts.append(f'<div style="color:#f5c542;font-weight:600;margin-top:6px">{html.escape(e["rel"])}</div>')
            parts.append(_diff_html(e["diff"] or f"+ (new file: {e['rel']})"))
        self.diffs.setHtml("".join(parts))
        n = len(edits)
        self.files_label.setText(f"{n} file{'s' if n != 1 else ''}, nothing written yet")
        self.yes.setText("Approve" if n == 1 else f"Approve all {n}")
        self.approve_card.show()
        self.scroll.setMaximumHeight(220)
        self.raise_()

    def clear_edits(self):
        self.approve_card.hide()
        self.scroll.setMaximumHeight(16777215)

    # ── memory offers
    def offer_memory(self, question_line, fact):
        self.mem_fact = fact
        self.memtext.setText(f"{question_line}  “{fact}”")
        self.memyes.show()
        self.memno.show()
        self.memrow.show()

    def settle_memory(self, line):
        self.memtext.setText(line)
        self.memyes.hide()
        self.memno.hide()

    def clear_memory_offer(self):
        self.mem_fact = ""
        self.memrow.hide()

    # ── showing and hiding
    def place_near(self, anchor, corner):
        """First time only: open beside the spider. After that it stays where you put it."""
        if self.placed:
            return
        screen = QApplication.primaryScreen().availableGeometry()
        sx, sy = corner
        w, h = self.width(), self.height()
        x = anchor.left() - w - 8 if sx > 0 else anchor.right() + 8
        y = anchor.bottom() - h if sy > 0 else anchor.top()
        x = max(screen.left() + 4, min(x, screen.right() - w - 4))
        y = max(screen.top() + 4, min(y, screen.bottom() - h - 4))
        self.move(int(x), int(y))

    def restore(self, geom):
        if isinstance(geom, (list, tuple)) and len(geom) == 4:
            x, y, w, h = (int(v) for v in geom)
            screen = QApplication.primaryScreen().availableGeometry()
            if screen.intersects(QRect(x, y, w, h)):
                self.setGeometry(x, y, max(340, w), max(360, h))
                self.placed = True

    def geom(self):
        g = self.geometry()
        return [g.x(), g.y(), g.width(), g.height()]

    def open_chat(self, intro=""):
        if intro:
            self.note(intro)
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def close_chat(self):
        self.hide()

    def hideEvent(self, e):
        self.closed.emit()
        super().hideEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.mode != "approve":
            self.close_chat()
        else:
            super().keyPressEvent(e)

    # ── input
    def _submit(self):
        if self.busy:
            return
        q = self.input.toPlainText().strip()
        if q:
            self.input.clear()
            self.asked.emit(q)

    def _send_or_stop(self):
        if self.busy:
            self.stop_requested.emit()
        else:
            self._submit()

    def _track_follow(self, v):
        sb = self.scroll.verticalScrollBar()
        self.follow = v >= sb.maximum() - 30

    def _stick_bottom(self, _lo, hi):
        if self.follow:
            self.scroll.verticalScrollBar().setValue(hi)
