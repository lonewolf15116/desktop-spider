"""The web: one leg per thing the spider pulls in for an answer, drawn live at the top of the chat.

Inspired by Prompt Spider: every input gets its own leg, coloured by route.
  code  (green) — pulled locally: project overview, your last file, test output, memory, files the model asked for
  model (blue)  — the model writing the reply
  you   (gold)  — an edit waiting for your Approve
A leg is dashed and moving while it pulls, turns solid when its thing lands, and snaps (red) if it fails.
"""
import math
import time

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget

ROUTE = {"code": QColor("#4fd38a"), "model": QColor("#5aa9ff"), "you": QColor("#f5c542")}
FAIL = QColor("#ff6b6b")
THEMES = {
    "zip": dict(text="#e7eef0", muted="#8796a0", tag="#1b2027", body="#20262e", ring="#22d3c5", eye="#22d3c5"),
    "vesper": dict(text="#e9e4d8", muted="#8b929e", tag="#181b22", body="#1a1d24", ring="{accent}", eye="{accent}"),
    "nib": dict(text="#1a1a1a", muted="#6b6b6b", tag="#ffffff", body="#111111", ring="#111111", eye="#f5c542"),
}


class Leg:
    __slots__ = ("key", "label", "route", "state", "born", "landed", "order")

    def __init__(self, key, label, route, order):
        self.key, self.label, self.route, self.order = key, label, route, order
        self.state = "pulling"
        self.born = time.time()
        self.landed = 0.0


class WebStrip(QWidget):
    H = 118

    def __init__(self):
        super().__init__()
        self.setFixedHeight(self.H)
        self.legs = {}
        self.theme = {k: QColor(v) for k, v in THEMES["zip"].items()}
        self.font = QFont("Segoe UI", 8)
        self.small = QFont("Segoe UI", 7)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.setToolTip("Each leg is something I pulled in for this answer.\n"
                        "Green: read on your laptop · Blue: the model · Gold: waiting for your Approve")

    # ── look
    def style_for(self, key, accent):
        pal = THEMES.get(key, THEMES["zip"])
        self.theme = {k: QColor(v.format(accent=accent)) for k, v in pal.items()}
        self.update()

    # ── legs
    def reset(self):
        self.legs = {}
        self.update()

    def pull(self, key, label, route="code", state="pulling"):
        leg = self.legs.get(key)
        if leg is None:
            leg = self.legs[key] = Leg(key, label, route, len(self.legs))
        leg.label = label or leg.label
        self.set_state(key, state)

    def set_state(self, key, state):
        leg = self.legs.get(key)
        if leg is None:
            return
        if state in ("done", "fail") and leg.state == "pulling":
            leg.landed = time.time()
        leg.state = state
        if not self.timer.isActive():
            self.timer.start(33)
        self.update()

    def counts(self):
        out = {"code": 0, "model": 0, "you": 0}
        for leg in self.legs.values():
            out[leg.route] = out.get(leg.route, 0) + 1
        return out

    def busy(self):
        return any(l.state == "pulling" for l in self.legs.values())

    def _tick(self):
        now = time.time()
        if not self.busy() and all(now - l.landed > 0.6 for l in self.legs.values()):
            self.timer.stop()
        self.update()

    # ── layout: tags in columns to the right of the spider, newest last
    def _layout(self, fm):
        top, row_h, x0 = 26, 22, 112
        rows = max(1, (self.H - top - 4) // row_h)
        legs = sorted(self.legs.values(), key=lambda l: l.order)
        placed, x, col, extra = [], x0, [], 0
        for leg in legs:
            w = min(150, fm.horizontalAdvance(leg.label) + 18)
            if len(col) == rows:
                x += max(c[1] for c in col) + 26
                col = []
            if x + w > self.width() - 6:
                extra += 1
                continue
            y = top + len(col) * row_h + (self.H - top - rows * row_h) // 2
            col.append((leg, w))
            placed.append((leg, QRectF(x, y, w, 17)))
        return placed, extra

    def paintEvent(self, _):
        if not self.legs:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        th, now = self.theme, time.time()
        fm = QFontMetrics(self.font)
        p.setFont(self.font)
        placed, extra = self._layout(fm)
        sx, sy = 46.0, self.H / 2 + 8

        # threads first, under everything
        for leg, rect in placed:
            col = FAIL if leg.state == "fail" else ROUTE.get(leg.route, ROUTE["code"])
            age = now - leg.landed if leg.landed else 0
            slide = 0.0 if leg.state == "pulling" else max(0.0, 1 - age / 0.35)      # a tug as it lands
            end = QPointF(rect.left() + 10 * slide, rect.center().y())
            path = QPainterPath(QPointF(sx, sy))
            path.cubicTo(QPointF(sx + 48, sy), QPointF(end.x() - 46, end.y()), end)
            if leg.state == "pulling":
                pen = QPen(col, 1.3, Qt.CustomDashLine)
                pen.setDashPattern([3, 4])
                pen.setDashOffset(-((now * 22) % 7))         # dashes run towards the spider
                c = QColor(col)
                c.setAlpha(210)
                pen.setColor(c)
            elif leg.state == "fail":
                cut = path.pointAtPercent(0.55)
                path = QPainterPath(QPointF(sx, sy))
                path.cubicTo(QPointF(sx + 30, sy), QPointF(cut.x() - 20, cut.y()), cut)
                pen = QPen(col, 1.2)
            else:
                c = QColor(col)
                c.setAlpha(150)
                pen = QPen(c, 1.2 + 0.8 * slide)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

        # tags
        for leg, rect in placed:
            col = FAIL if leg.state == "fail" else ROUTE.get(leg.route, ROUTE["code"])
            age = now - leg.landed if leg.landed else 0
            slide = 0.0 if leg.state == "pulling" else max(0.0, 1 - age / 0.35)
            r = rect.translated(10 * slide, 0)
            bg = QColor(th["tag"])
            fill = QColor(col)
            fill.setAlpha(46 if leg.state == "done" else 18)
            p.setPen(QPen(col if leg.state != "pulling" else _alpha(col, 140), 1))
            p.setBrush(bg)
            p.drawRoundedRect(r, 5, 5)
            p.setBrush(fill)
            p.drawRoundedRect(r, 5, 5)
            p.setPen(th["text"] if leg.state != "pulling" else th["muted"])
            txt = fm.elidedText(leg.label, Qt.ElideMiddle, int(r.width() - 12))
            p.drawText(r.adjusted(6, 0, -6, 0), Qt.AlignVCenter | Qt.AlignLeft, txt)
        if extra:
            p.setPen(th["muted"])
            p.drawText(QRectF(self.width() - 60, self.H - 18, 56, 14), Qt.AlignRight, f"+{extra} more")

        self._spider(p, sx, sy, now)

        # counters, Prompt Spider style
        p.setFont(self.small)
        x = self.width() - 6
        for route, label in (("you", "you"), ("model", "model"), ("code", "code")):
            n = self.counts().get(route, 0)
            s = f"{label} {n}"
            w = QFontMetrics(self.small).horizontalAdvance(s)
            x -= w
            p.setPen(ROUTE[route] if n else th["muted"])
            p.drawText(QRectF(x, 4, w, 14), Qt.AlignRight | Qt.AlignVCenter, s)
            x -= 12
        p.setPen(th["muted"])
        p.drawText(QRectF(8, 4, 200, 14), Qt.AlignLeft | Qt.AlignVCenter,
                   "pulling…" if self.busy() else f"{len(self.legs)} legs pulled")
        p.end()

    def _spider(self, p, x, y, now):
        """A small spider at the hub: eight legs, the front ones twitching while anything pulls."""
        th = self.theme
        busy = self.busy()
        p.setPen(QPen(th["muted"], 1.4))
        for i in range(4):
            for side in (-1, 1):
                a = math.radians(-60 + i * 40) * side
                wig = math.sin(now * 14 + i) * 0.18 if busy else 0
                kx, ky = x + side * 14 * math.cos(a + wig) * 0.9, y + 12 * math.sin(a + wig) - 6
                fx, fy = x + side * 24 * math.cos(a + wig), y + 18 * math.sin(a + wig) + 2
                path = QPainterPath(QPointF(x, y))
                path.quadTo(QPointF(kx, ky - 6), QPointF(fx, fy))
                p.drawPath(path)
        p.setPen(QPen(th["ring"], 1.4))
        p.setBrush(th["body"])
        p.drawEllipse(QPointF(x, y), 10, 9)
        p.setPen(Qt.NoPen)
        p.setBrush(th["eye"])
        for dx in (-3.6, 3.6):
            p.drawEllipse(QPointF(x + dx, y - 1.5), 2.2, 2.2)


def _alpha(c, a):
    c = QColor(c)
    c.setAlpha(a)
    return c
