"""The memory panel: everything the spider knows about you, with a forget button on each line."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

STYLE = {
    "zip": """
        QWidget#panel {{ background: #121519; }}
        QLabel {{ color: #e7eef0; font-size: 10pt; font-family: "Segoe UI", sans-serif; }}
        QLabel#title {{ color: #22d3c5; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }}
        QLabel#hint, QLabel#meta {{ color: #8796a0; font-size: 8.5pt; }}
        QLabel#kind {{ color: #ff8a3d; font-size: 7.5pt; letter-spacing: 1px; }}
        QFrame#item {{ background: #1b2027; border: 1px solid rgba(34,211,197,60); border-radius: 8px; }}
        QLineEdit {{ background: #1b2027; color: #e7eef0; border: 1px solid rgba(34,211,197,80);
                     border-radius: 8px; padding: 6px 8px; font-size: 10pt; }}
        QPushButton {{ background: transparent; color: #e7eef0; border: 1px solid rgba(34,211,197,80);
                       border-radius: 7px; padding: 4px 10px; font-size: 9pt; }}
        QPushButton#add {{ background: #ff8a3d; color: #1d0e03; border: none; font-weight: 600; }}
        QPushButton#forget {{ border: none; color: #8796a0; }}
        QPushButton#forget:hover {{ color: #ff7b7b; }}
        QCheckBox {{ color: #c9d3d8; font-size: 9pt; }}
        QScrollArea, QWidget#list {{ background: transparent; border: none; }}
    """,
    "vesper": """
        QWidget#panel {{ background: #0f1116; }}
        QLabel {{ color: #e9e4d8; font-size: 10pt; }}
        QLabel#title {{ color: {accent}; font-size: 9pt; letter-spacing: 2px; }}
        QLabel#hint, QLabel#meta {{ color: #8b929e; font-size: 8.5pt; }}
        QLabel#kind {{ color: {accent}; font-size: 7.5pt; letter-spacing: 1px; }}
        QFrame#item {{ background: rgba(255,255,255,8); border: 1px solid rgba(255,255,255,24); border-radius: 8px; }}
        QLineEdit {{ background: rgba(255,255,255,14); color: #f2efe8; border: 1px solid rgba(255,255,255,40);
                     border-radius: 8px; padding: 6px 8px; font-size: 10pt; }}
        QPushButton {{ background: transparent; color: #e9e4d8; border: 1px solid rgba(255,255,255,50);
                       border-radius: 7px; padding: 4px 10px; font-size: 9pt; }}
        QPushButton#add {{ background: #f5c542; color: #1b1505; border: none; font-weight: 600; }}
        QPushButton#forget {{ border: none; color: #8b929e; }}
        QPushButton#forget:hover {{ color: #ff7b7b; }}
        QCheckBox {{ color: #c9ced6; font-size: 9pt; }}
        QScrollArea, QWidget#list {{ background: transparent; border: none; }}
    """,
    "nib": """
        QWidget#panel {{ background: #fbf7ef; }}
        QLabel {{ color: #1a1a1a; font-size: 10pt; font-family: "Segoe Print", "Comic Sans MS", sans-serif; }}
        QLabel#title {{ color: #111; font-size: 10pt; font-weight: 700; }}
        QLabel#hint, QLabel#meta {{ color: #6b6b6b; font-size: 8.5pt; }}
        QLabel#kind {{ color: #a0761a; font-size: 7.5pt; font-weight: 700; }}
        QFrame#item {{ background: #ffffff; border: 2px solid #111; border-radius: 10px; }}
        QLineEdit {{ background: #ffffff; color: #111; border: 2px solid #111; border-radius: 10px;
                     padding: 6px 8px; font-size: 10pt; }}
        QPushButton {{ background: #ffffff; color: #111; border: 2px solid #111; border-radius: 9px;
                       padding: 4px 10px; font-size: 9pt; }}
        QPushButton#add {{ background: #f5c542; font-weight: 700; }}
        QPushButton#forget {{ border: none; color: #777; }}
        QPushButton#forget:hover {{ color: #d23c3c; }}
        QCheckBox {{ color: #222; font-size: 9pt; }}
        QScrollArea, QWidget#list {{ background: transparent; border: none; }}
    """,
}


class MemoryPanel(QWidget):
    changed = pyqtSignal()
    learning_toggled = pyqtSignal(bool)

    def __init__(self, memory):
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint)
        self.memory = memory
        self.setObjectName("panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.resize(380, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        self.title = QLabel(objectName="title")
        self.hint = QLabel(objectName="hint", wordWrap=True)
        lay.addWidget(self.title)
        lay.addWidget(self.hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list = QWidget(objectName="list")
        self.list_lay = QVBoxLayout(self.list)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(6)
        self.scroll.setWidget(self.list)
        lay.addWidget(self.scroll, 1)

        row = QHBoxLayout()
        self.entry = QLineEdit(placeholderText="Teach me something about you…")
        self.entry.returnPressed.connect(self._add)
        add = QPushButton("Add", objectName="add")
        add.clicked.connect(self._add)
        row.addWidget(self.entry, 1)
        row.addWidget(add)
        lay.addLayout(row)
        self.status = QLabel(objectName="hint", wordWrap=True)
        lay.addWidget(self.status)

        bottom = QHBoxLayout()
        self.pause = QCheckBox("Pause learning")
        self.pause.toggled.connect(lambda on: self.learning_toggled.emit(not on))
        self.wipe = QPushButton("Forget everything")
        self.wipe.clicked.connect(self._wipe)
        self._wipe_armed = False
        bottom.addWidget(self.pause)
        bottom.addStretch(1)
        bottom.addWidget(self.wipe)
        lay.addLayout(bottom)

    def style_for(self, persona_key, persona_name, accent, provider_label):
        self.setStyleSheet(STYLE.get(persona_key, STYLE["zip"]).format(accent=accent))
        self.setWindowTitle(f"{persona_name}'s memory")
        self.title.setText("WHAT I KNOW ABOUT YOU" if persona_key == "vesper" else "Stuff I know about you")
        self.hint.setText(f"Each line was approved by you. These are sent to {provider_label} with every question, "
                          "so I never keep keys, passwords or other secrets.")

    def set_learning(self, on):
        self.pause.blockSignals(True)
        self.pause.setChecked(not on)
        self.pause.blockSignals(False)

    def refresh(self):
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not self.memory.items:
            empty = QLabel("Nothing yet. Tell me something below, or just chat and I'll ask before I keep anything.",
                           objectName="hint", wordWrap=True)
            self.list_lay.addWidget(empty)
        for item in reversed(self.memory.items):
            self.list_lay.addWidget(self._row(item))
        self.list_lay.addStretch(1)
        n = len(self.memory.items)
        self.status.setText(f"{n} thing{'s' if n != 1 else ''} remembered.")
        self._wipe_armed = False
        self.wipe.setText("Forget everything")

    def _row(self, item):
        box = QFrame(objectName="item")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(10, 6, 6, 6)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(QLabel(item.get("kind", "about").upper(), objectName="kind"))
        text = QLabel(item["text"], wordWrap=True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(text)
        how = "you told me" if item.get("source") == "told" else "I noticed, you agreed"
        col.addWidget(QLabel(f"{how} · {item.get('added', '')}", objectName="meta"))
        lay.addLayout(col, 1)
        forget = QPushButton("Forget", objectName="forget")
        forget.clicked.connect(lambda _, i=item["id"]: self._forget(i))
        lay.addWidget(forget, 0, Qt.AlignTop)
        return box

    def _add(self):
        text = self.entry.text().strip()
        if not text:
            return
        ok, why = self.memory.add(text, source="told")
        if ok:
            self.entry.clear()
            self.refresh()
            self.changed.emit()
        else:
            self.status.setText({"secret": "That looks like a secret, so I won't keep it.",
                                 "duplicate": "I already know that.",
                                 "too long": "Keep it under 300 characters."}.get(why, "I couldn't keep that."))

    def _forget(self, item_id):
        if self.memory.forget(item_id):
            self.refresh()
            self.changed.emit()

    def _wipe(self):
        if not self._wipe_armed:
            self._wipe_armed = True
            self.wipe.setText("Click again to forget all")
            return
        self.memory.forget_all()
        self.refresh()
        self.changed.emit()
