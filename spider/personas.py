"""The two personas: how they look (drawn with QPainter) and how they talk.

Both are drawn in a square widget. `corner` is the screen corner the widget sits in,
as (sx, sy) with +1 meaning right/bottom. The spider faces the inside of the screen.
"""
import math
import random

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QFont, QPainter, QPainterPath, QPen,
                         QRadialGradient)

ROUTE_COLORS = {"code": QColor("#4fd38a"), "claude": QColor("#5aa9ff"), "you": QColor("#f5c542")}


class SpiderState:
    """Everything a persona needs to know to draw itself."""

    def __init__(self):
        self.mode = "idle"          # idle, running, pass, fail, waiting, thinking
        self.focus = False
        self.mode_since = 0.0       # time the mode started (seconds)
        self.legs = {}              # leg name -> idle/running/pass/fail
        self.splats = []            # Nib's ink splats: (x, y, r, born)


def _a(color, alpha):
    c = QColor(color)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


class Persona:
    key = ""
    name = ""
    voice = ""                      # system-prompt voice for the model
    lines = {}

    def say(self, event, **kw):
        options = self.lines.get(event)
        if not options:
            return ""
        text = random.choice(options) if isinstance(options, list) else options
        try:
            return text.format(**kw)
        except (KeyError, IndexError):
            return text

    def draw(self, p, w, h, st, t, corner, accent):
        raise NotImplementedError

    # helpers shared by both
    @staticmethod
    def _facing(corner):
        sx, sy = corner
        return math.degrees(math.atan2(-sy, -sx)) + 90  # local -y points inward


# ───────────────────────────────────────────────────────────── Vesper
class Vesper(Persona):
    key = "vesper"
    name = "Vesper"
    voice = ("You are Vesper, a calm, precise and slightly mysterious coding companion. "
             "Speak briefly: one to four short sentences unless code is needed. You notice "
             "everything and never fuss. A thread or weaving image is welcome now and then, "
             "never more than one per reply.")
    lines = {
        "welcome": "I'm here. Show me where to weave.",
        "no_folder": "Show me a folder to watch. Right-click me.",
        "no_key": "I need your {provider} key to speak. Put it after {var}= in the .env file.",
        "pass": ["All threads hold.", "All threads hold. {n} of {n}."],
        "fail": "One thread snapped. {test}, line {line}.",
        "fail_noline": "One thread snapped. {test}.",
        "syntax": "A knot in {file}, line {line}.",
        "no_tests": "No tests to hold the web together yet.",
        "thinking": "Following the thread…",
        "needs_approval": "I've woven the fix. Shall I place it?",
        "approved": "Placed. Testing it now.",
        "rejected": "Unwoven. Nothing changed.",
        "long_session": "You've been weaving for {hours} hours. Rest your hands.",
        "idle": ["The web is quiet.", "Still threads. Good threads.", "I'm watching."],
        "error": "Something tangled: {msg}",
        "remember_offer": "Shall I keep this thread?",
        "noticed_offer": "I've noticed something. Shall I keep it?",
        "remembered": "Kept.",
        "not_now": "Let it drift, then.",
        "secret_refused": "That looks like a secret. Some threads I won't keep.",
        "already_known": "I already hold that thread.",
        "reminder": "A thread you asked me to pull: {text}",
        "reminder_set": "I'll tug the thread {when}: {text}",
        "noted": "Noted.",
        "welcome_back": "Welcome back. We were weaving {project}.",
        "reading": "Reading the paper…",
        "synced": "Your memory is woven across your devices.",
        "phone_on": "Your phone can find me now.",
    }

    def draw(self, p, w, h, st, t, corner, accent):
        sx, sy = corner
        accent = QColor(accent)
        focus = st.focus
        # 1. the web in the corner, re-spun strand by strand
        wc = QPointF(w if sx > 0 else 0, h if sy > 0 else 0)
        base = math.atan2(-sy, -sx)
        strands = 9
        reach = min(w, h) * 1.05
        cycle = 48.0
        prog = (t % cycle) / cycle
        web_alpha = 25 if focus else 55
        p.setPen(QPen(_a("#dfe6f0", web_alpha), 0.8))
        angs = [base - math.pi / 4 + (math.pi / 2) * i / (strands - 1) for i in range(strands)]
        for a in angs:
            p.drawLine(wc, QPointF(wc.x() + math.cos(a) * reach, wc.y() + math.sin(a) * reach))
        rings, total = 7, 7 * (strands - 1)
        drawn = int(prog * 1.3 * total)
        k = 0
        for r in range(rings):
            rad = reach * (0.18 + 0.12 * r)
            for i in range(strands - 1):
                if k >= drawn:
                    break
                a1, a2 = angs[i], angs[i + 1]
                p.drawLine(QPointF(wc.x() + math.cos(a1) * rad, wc.y() + math.sin(a1) * rad),
                           QPointF(wc.x() + math.cos(a2) * rad * 0.985, wc.y() + math.sin(a2) * rad * 0.985))
                k += 1

        cx, cy = w * 0.5 + sx * w * 0.08, h * 0.5 + sy * h * 0.08
        pulse = 0.5 + 0.5 * math.sin(t * 2.2)

        # 2. threads to the screen edge, coloured by route
        threads = []
        if st.mode == "running":
            threads = [("code", -1), ("code", 1)]
        elif st.mode == "thinking":
            threads = [("claude", -1), ("claude", 1)]
        elif st.mode == "waiting":
            threads = [("you", 0)]

        p.save()
        p.translate(cx, cy)
        p.rotate(self._facing(corner))
        scale = 0.62 if focus else 1.0
        p.scale(scale, scale)

        # 3. legs (needle-thin, bracket joints)
        leg_pen = QPen(_a("#d6deea", 70 if focus else 210), 1.3)
        leg_pen.setCapStyle(Qt.RoundCap)
        bracket_font = QFont("Consolas", 7)
        tips = {}
        leg_angles = (-58, -22, 14, 48)
        for side in (-1, 1):
            for i in range(4):
                sway = 0 if focus else math.sin(t * 1.3 + i * 0.9 + side) * 2.5
                th = math.radians(leg_angles[i] + sway)
                base_pt = QPointF(side * 8, -15 + i * 4)
                lift = -16 if (i == 0 and threads and st.mode in ("running", "thinking")) else 0
                l1, l2 = 26, 26
                knee = QPointF(base_pt.x() + side * math.cos(th) * l1,
                               base_pt.y() + math.sin(th) * l1 - 15 + lift)
                foot = QPointF(base_pt.x() + side * math.cos(th) * (l1 + l2),
                               base_pt.y() + math.sin(th) * (l1 + l2) + 8 + lift * 1.5)
                if not focus:   # dark underlay keeps legs visible on light screens
                    under = QPen(_a("#05070a", 110), 3.2)
                    under.setCapStyle(Qt.RoundCap)
                    p.setPen(under)
                    p.drawLine(base_pt, knee)
                    p.drawLine(knee, foot)
                p.setPen(leg_pen)
                p.drawLine(base_pt, knee)
                p.drawLine(knee, foot)
                if not focus:
                    p.setPen(_a(accent, 150 + 80 * pulse))
                    p.setFont(bracket_font)
                    p.drawText(QRectF(knee.x() - 5, knee.y() - 6, 10, 12), Qt.AlignCenter,
                               "{" if side < 0 else "}")
                tips[(side, i)] = foot

        # 4. body: smoked glass with amber veins
        def glass(rect, alpha_scale=1.0):
            g = QRadialGradient(rect.center() + QPointF(-rect.width() * 0.2, -rect.height() * 0.25),
                                rect.width() * 0.75)
            g.setColorAt(0, _a("#4a515e", 235 * alpha_scale))
            g.setColorAt(0.55, _a("#1d2129", 240 * alpha_scale))
            g.setColorAt(1, _a("#0c0e12", 245 * alpha_scale))
            return QBrush(g)

        ceph = QRectF(-13, -26, 26, 24)
        abdo = QRectF(-19, -4, 38, 50)
        if focus:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(_a("#cfd6e2", 70), 1.2))
            p.drawEllipse(ceph)
            p.drawEllipse(abdo)
        else:
            p.setPen(QPen(_a("#ffffff", 45), 1))
            p.setBrush(glass(abdo))
            p.drawEllipse(abdo)
            p.setBrush(glass(ceph))
            p.drawEllipse(ceph)
            # veins
            vein = QPainterPath(QPointF(0, -1))
            vein.cubicTo(QPointF(2, 12), QPointF(-2, 26), QPointF(0, 42))
            for yb, d in ((10, 1), (18, -1), (27, 1), (33, -1)):
                vein.moveTo(0, yb)
                vein.quadTo(QPointF(d * 8, yb + 3), QPointF(d * 13, yb + 9))
            glow = QPen(_a(accent, 55 + 50 * pulse), 4.5)
            glow.setCapStyle(Qt.RoundCap)
            p.setBrush(Qt.NoBrush)
            p.setPen(glow)
            p.drawPath(vein)
            core = QPen(_a(accent, 170 + 85 * pulse), 1.3)
            core.setCapStyle(Qt.RoundCap)
            p.setPen(core)
            p.drawPath(vein)
            # eyes
            p.setPen(Qt.NoPen)
            for ex, ey, er in ((-4, -21, 2.0), (4, -21, 2.0), (-7.5, -18, 1.3), (7.5, -18, 1.3)):
                p.setBrush(_a(accent, 120))
                p.drawEllipse(QPointF(ex, ey), er + 1.6, er + 1.6)
                p.setBrush(_a("#ffe9bf", 255))
                p.drawEllipse(QPointF(ex, ey), er, er)
            # a crack of light when a test fails
            if st.mode == "fail":
                p.setPen(QPen(_a("#ff6b6b", 200 * pulse + 40), 1.2))
                crack = QPainterPath(QPointF(-10, 8))
                crack.lineTo(-4, 14)
                crack.lineTo(-8, 20)
                crack.lineTo(-2, 27)
                p.drawPath(crack)
        p.restore()

        # 5. draw threads in screen space from the lifted front legs to the inner edge
        if threads and not focus:
            ang = math.radians(self._facing(corner))
            for route, side in threads:
                col = ROUTE_COLORS[route]
                if side == 0:   # a single gold thread hanging from the body
                    start = QPointF(cx, cy)
                    end = QPointF(cx - sx * w * 0.42, cy - sy * h * 0.05)
                    sway = math.sin(t * 1.6) * 4
                    end += QPointF(0, sway)
                else:
                    lx, ly = side * 40, -52
                    rx = lx * math.cos(ang) - ly * math.sin(ang)
                    ry = lx * math.sin(ang) + ly * math.cos(ang)
                    start = QPointF(cx + rx, cy + ry)
                    end = QPointF(0 if sx > 0 else w, start.y() + side * 10) if abs(sx) >= abs(sy) \
                        else QPointF(start.x() + side * 10, 0 if sy > 0 else h)
                p.setPen(QPen(_a(col, 70 + 60 * pulse), 4))
                p.drawLine(start, end)
                p.setPen(QPen(_a(col, 200 + 55 * pulse), 1.2))
                p.drawLine(start, end)
                if side == 0:
                    p.setBrush(_a(col, 230))
                    p.setPen(Qt.NoPen)
                    p.drawEllipse(end, 3 + 1.5 * pulse, 3 + 1.5 * pulse)


# ───────────────────────────────────────────────────────────── Nib
class Nib(Persona):
    key = "nib"
    name = "Nib"
    voice = ("You are Nib, a warm, curious and cheeky coding companion. Keep replies short and "
             "friendly, celebrate small wins, and say plainly when you're not sure. A little "
             "playfulness is good; never let it get in the way of the answer.")
    lines = {
        "welcome": "Hi! I'm Nib. Point me at a project?",
        "no_folder": "Right-click me and pick a project folder!",
        "no_key": "I need your {provider} key to think out loud! Add it after {var}= in .env.",
        "pass": ["Green! {n} passing. Wiggle earned.", "All green! *wiggle*"],
        "fail": "Oops, {test} tripped at line {line}. Want me to look?",
        "fail_noline": "Oops, {test} tripped. Want me to look?",
        "syntax": "Uh-oh, something's off in {file}, line {line}.",
        "no_tests": "No tests found yet. Want to write one together?",
        "thinking": "Hmm, thinking…",
        "needs_approval": "I wrote a fix. Peek before I touch anything?",
        "approved": "Done! Running the tests…",
        "rejected": "Okay, binned it. Nothing touched.",
        "long_session": "{hours} hours straight! Water break? I'll guard the code.",
        "idle": ["*blinks*", "Still here!", "Psst. Commit lately?"],
        "error": "Eek, that didn't work: {msg}",
        "remember_offer": "Want me to remember that?",
        "noticed_offer": "I spotted a pattern! Remember it?",
        "remembered": "Got it, remembered!",
        "not_now": "No worries, forgotten already.",
        "secret_refused": "Ooh, that looks like a secret. I'm not keeping that one!",
        "already_known": "I knew that one already!",
        "reminder": "Hey! You asked me to remind you: {text}",
        "reminder_set": "Got it, I'll poke you {when}: {text}",
        "noted": "Jotted down!",
        "welcome_back": "You're back! We were on {project}.",
        "reading": "Ooh, a paper! Reading…",
        "synced": "Memory synced across your devices!",
        "phone_on": "Phone link is on! Come find me.",
    }

    def draw(self, p, w, h, st, t, corner, accent):
        sx, sy = corner
        accent = QColor(accent)
        rng = random.Random(7)
        since = t - st.mode_since
        cx, cy = w * 0.5 + sx * w * 0.07, h * 0.5 + sy * h * 0.07
        bob = 0 if st.focus else math.sin(t * 1.4) * 3
        cy += bob
        rot = 0.0
        if st.mode == "pass" and since < 1.4:
            rot = math.sin(since * 26) * 9 * (1 - since / 1.4)
        r = 34.0

        # ink splats after a pass (behind him)
        for (x, y, rr, born) in st.splats:
            age = t - born
            if age > 2.5:
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(_a("#111111", 200 * (1 - age / 2.5)))
            p.drawEllipse(QPointF(x, y), rr, rr)
            for k in range(4):
                a = rng.random() * 6.28
                p.drawEllipse(QPointF(x + math.cos(a) * rr * 1.4, y + math.sin(a) * rr * 1.4),
                              rr * 0.25, rr * 0.25)

        p.save()
        p.translate(cx, cy)
        p.rotate(rot)  # Nib stays upright and faces you

        ink = QColor("#0d0d0d")
        if st.focus:
            # curled up asleep
            breathe = 1 + 0.035 * math.sin(t * 1.5)
            p.scale(breathe * 0.85, breathe * 0.85)
            p.setPen(QPen(ink, 2.6))
            p.setBrush(QColor("#171717"))
            p.drawPath(self._wobbly(r, t, 0.6))
            p.setPen(QPen(_a(accent, 160), 2))
            p.drawLine(QPointF(-10, -8), QPointF(-3, -8))
            p.drawLine(QPointF(3, -8), QPointF(10, -8))
            p.restore()
            p.setPen(_a("#9aa0a6", 150 + 100 * math.sin(t)))
            f = QFont("Comic Sans MS", 11)
            f.setItalic(True)
            p.setFont(f)
            zy = (t * 12) % 30
            p.drawText(QPointF(cx - sx * 34, cy - sy * 30 - zy), "z")
            return

        # legs: short inky strokes, tapping one after another while tests run
        leg_pen = QPen(ink, 4.2)
        leg_pen.setCapStyle(Qt.RoundCap)
        p.setPen(leg_pen)
        tapping = st.mode == "running"
        tap_idx = int(t * 9) % 8
        droop = 8 if st.mode == "fail" else 0
        for side in (-1, 1):
            for i in range(4):
                n = (0 if side < 0 else 4) + i
                lift = -9 if tapping and n == tap_idx else 0
                y0 = -14 + i * 9
                path = QPainterPath(QPointF(side * r * 0.8, y0))
                path.quadTo(QPointF(side * (r + 16), y0 - 14 + i * 4 + lift),
                            QPointF(side * (r + 22), y0 + 10 + i * 6 + lift + droop))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)

        # body
        p.setPen(QPen(ink, 2.8))
        p.setBrush(QColor("#171717"))
        p.drawPath(self._wobbly(r, t, 1.0))
        p.setPen(QPen(_a("#ffffff", 45), 2))
        p.drawArc(QRectF(-r * 0.7, -r * 0.75, r * 1.0, r * 0.9), 100 * 16, 60 * 16)

        # eyes: one glowing cluster, blinking now and then
        blink = (t % 4.7) < 0.14
        glow = 0.6 + 0.4 * math.sin(t * 3) if st.mode == "thinking" else 1.0
        for ex, ey, er in ((-8, -10, 6.0), (8, -10, 6.0), (-15, -2, 3.2), (15, -2, 3.2)):
            if blink:
                p.setPen(QPen(_a(accent, 230), 2))
                p.drawLine(QPointF(ex - er, ey), QPointF(ex + er, ey))
                continue
            p.setPen(Qt.NoPen)
            p.setBrush(_a(accent, 70 * glow))
            p.drawEllipse(QPointF(ex, ey), er + 3, er + 3)
            p.setBrush(_a(accent, 255 * glow))
            p.drawEllipse(QPointF(ex, ey), er, er)
            p.setBrush(_a("#ffffff", 230))
            p.drawEllipse(QPointF(ex - er * 0.35, ey - er * 0.35), er * 0.3, er * 0.3)

        # mouth: yawn when idle, small "o" when it fails
        yawn = st.mode == "idle" and (t % 23) < 1.6
        if yawn or st.mode == "fail":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#3a1f1f"))
            hgt = 7 * math.sin(min(1, (t % 23) / 1.6) * math.pi) if yawn else 3.5
            p.drawEllipse(QPointF(0, 8), 4.5, max(1.5, hgt))
        p.restore()

        # the little approval sign, held up above his head
        if st.mode == "waiting":
            sw, sh = 46, 24
            sxp = cx - sx * 20 - sw / 2
            syp = cy - sy * 58 - sh / 2 + math.sin(t * 3) * 2
            p.setPen(QPen(ink, 2))
            p.drawLine(QPointF(sxp + sw / 2, syp + sh), QPointF(cx - sx * 10, cy - sy * 30))
            p.setBrush(QColor("#fbf7ef"))
            p.drawRoundedRect(QRectF(sxp, syp, sw, sh), 5, 5)
            p.setFont(QFont("Segoe UI Symbol", 11, QFont.Bold))
            p.setPen(QColor("#d4a017"))
            p.drawText(QRectF(sxp, syp, sw / 2, sh), Qt.AlignCenter, "✓")
            p.setPen(QColor("#d23c3c"))
            p.drawText(QRectF(sxp + sw / 2, syp, sw / 2, sh), Qt.AlignCenter, "✗")
        if st.mode == "thinking":
            p.setPen(Qt.NoPen)
            for k in range(3):
                a = 120 + 135 * (0.5 + 0.5 * math.sin(t * 5 - k))
                p.setBrush(_a(ROUTE_COLORS["claude"], a))
                p.drawEllipse(QPointF(cx - sx * (30 + k * 10), cy - sy * 48), 3, 3)

    @staticmethod
    def _wobbly(r, t, amt):
        path = QPainterPath()
        n = 48
        for i in range(n + 1):
            a = 2 * math.pi * i / n
            rr = r * (1 + amt * (0.035 * math.sin(3 * a + 1.3) + 0.02 * math.sin(7 * a + t * 0.6)))
            pt = QPointF(math.cos(a) * rr, math.sin(a) * rr * 0.95)
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        return path





# ───────────────────────────────────────────────────────────── Zip
class Zip(Persona):
    """An original acrobatic jumping spider: big glossy eyes, charcoal fuzz, electric-teal markings.

    Drops in on a silk line, crouches before it pounces, flips when your tests pass.
    """
    key = "zip"
    name = "Zip"
    TEAL = QColor("#22d3c5")
    EMBER = QColor("#ff8a3d")
    voice = ("You are Zip, a quick, upbeat and confident coding companion with an acrobat's energy. "
             "Keep replies punchy and practical: lead with the fix or the answer, then the why in a line "
             "or two. Celebrate wins briefly. When you're unsure, say so straight away.")
    lines = {
        "welcome": "Zip here. Point me at a project and I'll keep watch.",
        "no_folder": "Give me a project folder to guard. Right-click me.",
        "no_key": "I need your {provider} key to jump in. Put it after {var}= in the .env file.",
        "pass": ["All {n} green. Stuck the landing!", "Clean run. {n} passing."],
        "fail": "{test} fell at line {line}. Want me to pounce on it?",
        "fail_noline": "{test} fell. Want me to pounce on it?",
        "syntax": "Tripwire in {file}, line {line}.",
        "no_tests": "No tests to guard yet. Want to write the first one?",
        "thinking": "On it…",
        "needs_approval": "Fix is ready. Your call: drop it in?",
        "approved": "In. Running the tests…",
        "rejected": "Scrapped. Nothing touched.",
        "long_session": "{hours} hours on the wall. Take a breather, I've got watch.",
        "idle": ["Scanning…", "All quiet on the web.", "Ready when you are."],
        "error": "Missed the jump: {msg}",
        "remember_offer": "Worth remembering?",
        "noticed_offer": "Spotted a pattern. Keep it?",
        "remembered": "Locked in.",
        "not_now": "Dropped it.",
        "secret_refused": "That looks like a secret. Not keeping it.",
        "already_known": "Already got that one.",
        "reminder": "Heads up: {text}",
        "reminder_set": "Got it. I'll ping you {when}: {text}",
        "noted": "Noted.",
        "welcome_back": "Back on the wall. We were on {project}.",
        "reading": "Reading the paper…",
        "synced": "Memory synced across your devices.",
        "phone_on": "Phone link's up. Come find me.",
    }

    def draw(self, p, w, h, st, t, corner, accent):
        sx, sy = corner
        since = t - st.mode_since
        teal, ember = QColor(self.TEAL), QColor(self.EMBER)
        cx = w * 0.5 + sx * w * 0.06
        ground = h * 0.80 if sy > 0 else h * 0.86
        body_y = ground - 52
        y_off, rot, squash, crouch = 0.0, 0.0, 1.0, 0.0
        silk_from_top = False

        # entrance: drop in on a silk line
        if t < 1.3:
            u = min(1.0, t / 1.3)
            ease = 1 - (1 - u) ** 3
            y_off = -(body_y + 60) * (1 - ease)
            silk_from_top = True
        elif st.focus:
            crouch = 10
        elif st.mode == "pass" and since < 1.1:
            u = since / 0.9
            if u < 1:
                y_off = -46 * 4 * u * (1 - u)
                rot = 360 * u * (1 if sx < 0 else -1)
                squash = 1.0
            else:
                squash = 1 - 0.18 * math.sin((since - 0.9) / 0.2 * math.pi)
        elif st.mode == "thinking":
            crouch = 8 + 2 * math.sin(t * 6)
        elif st.mode == "fail":
            crouch = 6
        elif st.mode == "running":
            crouch = -4
        else:
            hop_t = t % 13.0
            if hop_t < 0.45:
                u = hop_t / 0.45
                y_off = -18 * 4 * u * (1 - u)
            y_off += math.sin(t * 2.0) * 1.2

        breathe = 1 + 0.015 * math.sin(t * 2.4)
        by = body_y + crouch + y_off

        # threads: entrance silk, thinking (blue), waiting (gold)
        if silk_from_top:
            p.setPen(QPen(_a("#dfe9ee", 170), 1.2))
            p.drawLine(QPointF(cx, 0), QPointF(cx, by - 30))
        if st.mode in ("thinking", "waiting") and not st.focus:
            col = ROUTE_COLORS["claude" if st.mode == "thinking" else "you"]
            pulse = 0.5 + 0.5 * math.sin(t * 3)
            top = QPointF(cx - sx * 18, 0 if sy > 0 else h)
            p.setPen(QPen(_a(col, 70 + 60 * pulse), 4))
            p.drawLine(QPointF(cx, by - 28), top)
            p.setPen(QPen(_a(col, 210), 1.3))
            p.drawLine(QPointF(cx, by - 28), top)
            if st.mode == "waiting":
                drop = QPointF(cx - sx * 9, by - 50 + math.sin(t * 2.5) * 3)
                p.setPen(Qt.NoPen)
                p.setBrush(_a(col, 230))
                p.drawEllipse(drop, 4 + 1.5 * pulse, 4 + 1.5 * pulse)

        # ground shadow
        p.setPen(Qt.NoPen)
        shadow = max(0.25, 1 - abs(y_off) / 90)
        p.setBrush(_a("#000000", 60 * shadow))
        p.drawEllipse(QPointF(cx, ground + 4), 46 * shadow, 7 * shadow)

        p.save()
        p.translate(cx, by)
        p.rotate(rot)
        p.scale(breathe, breathe * squash)
        if st.focus:
            p.setOpacity(0.45)

        # legs: four a side, segmented, teal bands at the knees
        tucked = st.focus
        for side in (-1, 1):
            for i in range(4):
                base = QPointF(side * (20 + i * 3), -4 + i * 6)
                spread = (34 + i * 7) * (0.55 if tucked else 1.0)
                tap = -6 if st.mode == "running" and int(t * 8) % 8 == (i + (0 if side < 0 else 4)) else 0
                knee = QPointF(side * (spread + 2 + i * 4), -26 + i * 6 - crouch * 0.6 + tap)
                foot_y = (ground - by) - 2 if not tucked and abs(y_off) < 2 else 30 + i * 4
                foot = QPointF(side * (spread + 6 + i * 12), foot_y + tap)
                path = QPainterPath(base)
                path.lineTo(knee)
                path.lineTo(foot)
                p.setBrush(Qt.NoBrush)
                pen = QPen(QColor("#1b1f25"), 6.2 - i * 0.5)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                p.drawPath(path)
                pen = QPen(QColor("#3a414c"), 3.6 - i * 0.3)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                p.drawPath(path)
                p.setPen(Qt.NoPen)
                p.setBrush(teal)
                p.drawEllipse(knee, 3.0, 3.0)

        # abdomen peeking behind, with teal chevrons
        abdo = QRectF(-30, -62, 60, 50)
        g = QRadialGradient(QPointF(-8, -50), 40)
        g.setColorAt(0, QColor("#3a414c"))
        g.setColorAt(1, QColor("#15181d"))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(abdo)
        p.setPen(QPen(_a(teal, 220), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for k in range(3):
            yy = -54 + k * 9
            chev = QPainterPath(QPointF(-12 + k * 2, yy))
            chev.lineTo(0, yy + 5)
            chev.lineTo(12 - k * 2, yy)
            p.drawPath(chev)

        # head (cephalothorax): fuzzy rim, charcoal gradient
        head = QRectF(-40, -34, 80, 66)
        rng = random.Random(11)
        p.setPen(QPen(QColor("#2b3139"), 2, Qt.SolidLine, Qt.RoundCap))
        for k in range(72):
            a = 2 * math.pi * k / 72
            r1x, r1y = 38, 31
            r2 = 1 + 0.10 + 0.06 * rng.random()
            x1, y1 = math.cos(a) * r1x, math.sin(a) * r1y - 1
            p.drawLine(QPointF(x1, y1), QPointF(x1 * r2, y1 * r2))
        g = QRadialGradient(QPointF(-12, -18), 60)
        g.setColorAt(0, QColor("#4a525e"))
        g.setColorAt(0.6, QColor("#262b33"))
        g.setColorAt(1, QColor("#14171c"))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawEllipse(head)
        # teal crest across the top of the head
        crest = QPainterPath(QPointF(-26, -22))
        crest.cubicTo(QPointF(-10, -34), QPointF(10, -34), QPointF(26, -22))
        p.setPen(QPen(_a(teal, 230), 3.2, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawPath(crest)

        # eyes: two big glossy principal eyes, two side eyes, look toward the screen
        look = QPointF(-sx * 2.2, -sy * 1.2)
        blink = (t % 6.3) < 0.12 or st.mode == "fail"
        for ex in (-14, 14):
            c = QPointF(ex, -2)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#07080a"))
            p.drawEllipse(c, 13, 13)
            ring = QRadialGradient(c + look, 13)
            ring.setColorAt(0.0, QColor("#0b0d10"))
            ring.setColorAt(0.62, QColor("#0b0d10"))
            ring.setColorAt(0.80, _a(teal, 200))
            ring.setColorAt(1.0, QColor("#0b0d10"))
            p.setBrush(QBrush(ring))
            p.drawEllipse(c + look, 11, 11)
            p.setBrush(_a("#ffffff", 235))
            p.drawEllipse(c + QPointF(-4.5, -5) + look * 0.4, 3.6, 3.0)
            p.setBrush(_a("#ffffff", 120))
            p.drawEllipse(c + QPointF(4, 4) + look * 0.4, 1.6, 1.6)
            if blink:
                lid = QPainterPath(c + QPointF(-13, 0))
                lid.arcTo(QRectF(c.x() - 13, c.y() - 13, 26, 26), 180, -180)
                lid.closeSubpath()
                p.setBrush(QColor("#2a3038"))
                p.drawPath(lid)
        for ex, ey in ((-31, -6), (31, -6), (-24, -20), (24, -20)):
            p.setBrush(QColor("#07080a"))
            p.drawEllipse(QPointF(ex, ey), 4.2, 4.2)
            p.setBrush(_a("#ffffff", 200))
            p.drawEllipse(QPointF(ex - 1.2, ey - 1.4), 1.3, 1.1)

        # palps with ember tips
        for side in (-1, 1):
            p.setPen(QPen(QColor("#2b3139"), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(side * 8, 18), QPointF(side * 11, 28))
            p.setPen(Qt.NoPen)
            p.setBrush(ember)
            p.drawEllipse(QPointF(side * 11.5, 29.5), 3.4, 3.0)
        p.restore()

        # little marks: a red "!" on fail, a "z" in focus
        if st.mode == "fail" and not st.focus:
            p.setPen(QColor("#ff5d5d"))
            p.setFont(QFont("Segoe UI", 15, QFont.Black))
            p.drawText(QPointF(cx + 36 * (-sx), by - 40), "!")
        if st.focus:
            p.setPen(_a("#9aa0a6", 150 + 100 * math.sin(t)))
            f = QFont("Segoe UI", 11)
            f.setItalic(True)
            p.setFont(f)
            p.drawText(QPointF(cx - sx * 40, by - 40 - (t * 12) % 30), "z")


PERSONAS = {"zip": Zip(), "vesper": Vesper(), "nib": Nib()}
