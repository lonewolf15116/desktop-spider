"""The speech bubble: short lines next to the spider. Conversations live in the chat window (chat.py)."""
from PyQt5.QtCore import QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

STYLES = {
    "zip": """
        QFrame#card {{ background: rgba(18,21,25,240); border: 1px solid #22d3c5; border-radius: 12px; }}
        QLabel {{ color: #e7eef0; background: transparent; font-size: 10pt; font-family: "Segoe UI", sans-serif; }}
        QLabel#name {{ color: #22d3c5; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
    """,
    "vesper": """
        QFrame#card {{ background: rgba(14,16,22,238); border: 1px solid {accent}; border-radius: 12px; }}
        QLabel {{ color: #e9e4d8; background: transparent; font-size: 10pt; }}
        QLabel#name {{ color: {accent}; font-size: 8pt; letter-spacing: 2px; }}
    """,
    "nib": """
        QFrame#card {{ background: #fbf7ef; border: 2px solid #111111; border-radius: 16px; }}
        QLabel {{ color: #1a1a1a; background: transparent; font-size: 10pt;
                  font-family: "Segoe Print", "Comic Sans MS", sans-serif; }}
        QLabel#name {{ color: #111111; font-size: 8pt; font-weight: 700; }}
    """,
}


class Bubble(QWidget):
    clicked = pyqtSignal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMaximumWidth(300)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.card = QFrame(objectName="card")
        outer.addWidget(self.card)
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(12, 8, 12, 10)
        lay.setSpacing(4)
        self.name = QLabel(objectName="name")
        self.text = QLabel(wordWrap=True)
        self.text.setMaximumWidth(260)
        lay.addWidget(self.name)
        lay.addWidget(self.text)
        self.setCursor(Qt.PointingHandCursor)
        self.hide_timer = QTimer(self, singleShot=True)
        self.hide_timer.timeout.connect(self.close_bubble)
        self.mode = "hidden"
        self.anchor = QRect()
        self.corner = (1, 1)

    def style_for(self, persona_key, persona_name, accent):
        self.setStyleSheet(STYLES.get(persona_key, STYLES["zip"]).format(accent=accent))
        self.name.setText(persona_name.upper() if persona_key == "vesper" else persona_name)

    def say(self, line, ms=6000):
        self.mode = "say"
        self.text.setText(line)
        self._show()
        self.hide_timer.start(ms)
        return True

    def close_bubble(self):
        self.mode = "hidden"
        self.hide_timer.stop()
        self.hide()

    def mousePressEvent(self, e):
        self.close_bubble()
        self.clicked.emit()

    def place(self, anchor, corner):
        self.anchor, self.corner = anchor, corner
        if self.isVisible():
            self._reposition()

    def _show(self):
        self._reposition()
        self.show()
        self.raise_()

    def _reposition(self):
        self.adjustSize()
        a, (sx, sy) = self.anchor, self.corner
        w, h = self.width(), self.height()
        x = a.left() - w + 24 if sx > 0 else a.right() - 24
        y = a.top() - h + 30 if sy > 0 else a.bottom() - 30
        screen = QApplication.primaryScreen().availableGeometry()
        x = max(screen.left() + 4, min(x, screen.right() - w - 4))
        y = max(screen.top() + 4, min(y, screen.bottom() - h - 4))
        self.move(int(x), int(y))
