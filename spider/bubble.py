"""The speech bubble: short lines, the chat box, the approve/reject panel and memory offers."""
from PyQt5.QtCore import QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
import html

from PyQt5.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QTextBrowser, QVBoxLayout, QWidget)

STYLES = {
    "vesper": """
        QFrame#card {{ background: rgba(14,16,22,238); border: 1px solid {accent}; border-radius: 12px; }}
        QLabel, QTextBrowser {{ color: #e9e4d8; background: transparent; border: none; font-size: 10pt; }}
        QLabel#name {{ color: {accent}; font-size: 8pt; letter-spacing: 2px; }}
        QLineEdit {{ background: rgba(255,255,255,14); color: #f2efe8; border: 1px solid rgba(255,255,255,40);
                     border-radius: 8px; padding: 6px 8px; font-size: 10pt; }}
        QTextBrowser#diff {{ background: rgba(0,0,0,90); color: #d9dde4; border: 1px solid rgba(255,255,255,30);
                          border-radius: 6px; font-family: Consolas, monospace; font-size: 8.5pt; }}
        QPushButton {{ border-radius: 8px; padding: 6px 12px; font-size: 9.5pt; }}
        QPushButton#yes {{ background: #f5c542; color: #1b1505; border: none; font-weight: 600; }}
        QPushButton#no {{ background: transparent; color: #e9e4d8; border: 1px solid rgba(255,255,255,60); }}
        QFrame#memrow {{ background: rgba(245,197,66,22); border: 1px solid rgba(245,197,66,120); border-radius: 8px; }}
        QLabel#memtext {{ color: #f7e7b5; font-size: 9pt; }}
        QPushButton#memyes {{ background: #f5c542; color: #1b1505; border: none; padding: 4px 10px; font-size: 9pt; }}
        QPushButton#memno {{ background: transparent; color: #e9e4d8; border: none; padding: 4px 8px; font-size: 9pt; }}
    """,
    "nib": """
        QFrame#card {{ background: #fbf7ef; border: 2px solid #111111; border-radius: 16px; }}
        QLabel, QTextBrowser {{ color: #1a1a1a; background: transparent; border: none; font-size: 10pt;
                                font-family: "Segoe Print", "Comic Sans MS", sans-serif; }}
        QLabel#name {{ color: #111111; font-size: 8pt; font-weight: 700; }}
        QLineEdit {{ background: #ffffff; color: #111; border: 2px solid #111; border-radius: 10px;
                     padding: 6px 8px; font-size: 10pt; }}
        QTextBrowser#diff {{ background: #ffffff; color: #222; border: 1px solid #bbb; border-radius: 6px;
                          font-family: Consolas, monospace; font-size: 8.5pt; }}
        QPushButton {{ border-radius: 10px; padding: 6px 12px; font-size: 9.5pt; border: 2px solid #111; }}
        QPushButton#yes {{ background: #f5c542; color: #111; font-weight: 700; }}
        QPushButton#no {{ background: #ffffff; color: #111; }}
        QFrame#memrow {{ background: #fff3c4; border: 2px dashed #111; border-radius: 10px; }}
        QLabel#memtext {{ color: #111; font-size: 9pt; }}
        QPushButton#memyes {{ background: #f5c542; color: #111; padding: 4px 10px; font-size: 9pt; }}
        QPushButton#memno {{ background: transparent; color: #111; border: none; padding: 4px 8px; font-size: 9pt; }}
    """,
}


class Bubble(QWidget):
    asked = pyqtSignal(str)
    approved = pyqtSignal()
    rejected = pyqtSignal()
    mem_yes = pyqtSignal(str)
    mem_no = pyqtSignal(str)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(330)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.card = QFrame(objectName="card")
        outer.addWidget(self.card)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(8)
        self.name = QLabel(objectName="name")
        self.text = QLabel(wordWrap=True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.answer = QTextBrowser()
        self.answer.setOpenExternalLinks(True)
        
        self.diff = QTextBrowser()
        self.diff.setObjectName("diff")
        self.input = QLineEdit(placeholderText="Ask about your code…")
        self.input.returnPressed.connect(self._submit)
        row = QHBoxLayout()
        self.yes = QPushButton("Approve", objectName="yes")
        self.no = QPushButton("Reject", objectName="no")
        self.yes.clicked.connect(self.approved.emit)
        self.no.clicked.connect(self.rejected.emit)
        row.addStretch(1)
        row.addWidget(self.no)
        row.addWidget(self.yes)
        self.buttons = QWidget()
        self.buttons.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        # "Should I remember …?" row: shown alongside an answer, one fact at a time
        self.memrow = QFrame(objectName="memrow")
        mlay = QVBoxLayout(self.memrow)
        mlay.setContentsMargins(10, 6, 8, 6)
        mlay.setSpacing(4)
        self.memtext = QLabel(objectName="memtext", wordWrap=True)
        mbtns = QHBoxLayout()
        mbtns.setContentsMargins(0, 0, 0, 0)
        self.memyes = QPushButton("Remember", objectName="memyes")
        self.memno = QPushButton("Not now", objectName="memno")
        self.memyes.clicked.connect(lambda: self.mem_yes.emit(self.mem_fact))
        self.memno.clicked.connect(lambda: self.mem_no.emit(self.mem_fact))
        mbtns.addStretch(1)
        mbtns.addWidget(self.memno)
        mbtns.addWidget(self.memyes)
        mlay.addWidget(self.memtext)
        mlay.addLayout(mbtns)
        self.memrow.hide()
        self.mem_fact = ""
        for w in (self.name, self.text, self.answer, self.diff, self.memrow, self.input, self.buttons):
            lay.addWidget(w)
        self.hide_timer = QTimer(self, singleShot=True)
        self.hide_timer.timeout.connect(self._auto_hide)
        self.mode = "hidden"
        self.anchor = QRect()
        self.corner = (1, 1)

    def style_for(self, persona_key, persona_name, accent):
        self.setStyleSheet(STYLES[persona_key].format(accent=accent))
        self.name.setText(persona_name.upper() if persona_key == "vesper" else persona_name)

    def _only(self, *widgets):
        for w in (self.text, self.answer, self.diff, self.input, self.buttons):
            w.setVisible(w in widgets)

    def say(self, line, ms=6000):
        if self.mode in ("chat", "approve"):
            return False
        self.mode = "say"
        self.memrow.hide()
        self.text.setText(line)
        self._only(self.text)
        self._show()
        self.hide_timer.start(ms)
        return True

    def open_chat(self, intro=""):
        self.mode = "chat"
        self.hide_timer.stop()
        self.text.setText(intro)
        self._only(*( [self.text] if intro else [] ), self.input)
        self._show()
        self.activateWindow()
        self.input.setFocus()

    def show_thinking(self, line):
        self.text.setText(line)
        self._only(self.text, self.input)
        self.input.setEnabled(False)
        self._show()

    def show_answer(self, md):
        self.mode = "chat"
        self.input.setEnabled(True)
        self.answer.setMarkdown(md)
        self._fit(self.answer, 300)
        self._only(self.answer, self.input)
        self._show()
        self.input.setFocus()

    def show_edit(self, line, answer_md, diff):
        self.mode = "approve"
        self.hide_timer.stop()
        self.input.setEnabled(True)
        self.text.setText(line)
        self.answer.setMarkdown(answer_md)
        self._fit(self.answer, 160)
        self.diff.setHtml(self._diff_html(diff or "(new file)"))
        self._fit(self.diff, 260)
        widgets = [self.text, self.diff, self.buttons]
        if answer_md.strip():
            widgets.insert(1, self.answer)
        self._only(*widgets)
        self._show()

    @staticmethod
    def _fit(view, cap):
        doc = view.document()
        doc.setTextWidth(330 - 12 - 28 - 6)
        view.setFixedHeight(int(min(cap, max(36, doc.size().height() + 8))))

    @staticmethod
    def _diff_html(diff):
        rows = []
        for line in diff.splitlines():
            esc = html.escape(line) or "&nbsp;"
            if line.startswith("+") and not line.startswith("+++"):
                rows.append(f'<div style="background:rgba(79,211,138,0.22);color:#2fbf71">{esc}</div>')
            elif line.startswith("-") and not line.startswith("---"):
                rows.append(f'<div style="background:rgba(255,107,107,0.20);color:#e05252">{esc}</div>')
            elif line.startswith("@@"):
                rows.append(f'<div style="color:#5aa9ff">{esc}</div>')
            else:
                rows.append(f'<div style="color:#8a93a0">{esc}</div>')
        return '<pre style="font-family:Consolas,monospace;font-size:8.5pt;margin:0">' + "".join(rows) + "</pre>"

    def offer_memory(self, question_line, fact):
        """Show 'Should I remember: <fact>?' under whatever is open. Opens chat if nothing is."""
        self.mem_fact = fact
        self.memtext.setText(f"{question_line}\n“{fact}”")
        if self.mode not in ("chat", "approve"):
            self.mode = "chat"
            self.hide_timer.stop()
            self._only(self.input)
        self.memrow.show()
        self._show()

    def clear_memory_offer(self):
        self.mem_fact = ""
        self.memrow.hide()
        if self.isVisible():
            self._show()

    def close_bubble(self):
        self.mode = "hidden"
        self.memrow.hide()
        self.mem_fact = ""
        self.input.setEnabled(True)
        self.hide()

    def _submit(self):
        q = self.input.text().strip()
        if q:
            self.input.clear()
            self.asked.emit(q)

    def _auto_hide(self):
        if self.mode == "say":
            self.close_bubble()

    def place(self, anchor, corner):
        self.anchor, self.corner = anchor, corner
        if self.isVisible():
            self._reposition()

    def _show(self):
        self.adjustSize()
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self):
        self.adjustSize()
        a, (sx, sy) = self.anchor, self.corner
        w, h = self.width(), self.height()
        x = a.left() - w + 30 if sx > 0 else a.right() - 30
        y = a.bottom() - h - 40 if sy > 0 else a.top() + 40
        screen = QApplication.primaryScreen().availableGeometry()
        x = max(screen.left() + 4, min(x, screen.right() - w - 4))
        y = max(screen.top() + 4, min(y, screen.bottom() - h - 4))
        self.move(int(x), int(y))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.mode != "approve":
            self.close_bubble()
        else:
            super().keyPressEvent(e)
