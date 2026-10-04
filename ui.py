"""
FASTER — Voice Workspace  (ui.py)
Cyberpunk / neon redesign of the local speech-to-text dictation app.

Install:  pip install PyQt6 numpy sounddevice keyboard pyperclip faster-whisper
Run:      python ui.py

File layout (top to bottom):
  1. Config & helpers        6. Engine  (audio, whisper, hotkeys, voice commands)
  2. Theme + QSS builder     7. Pages   (Studio / Archive / Settings)
  3. Animation utilities     8. Chrome  (Sidebar, Topbar)
  4. Painted neon widgets    9. MainWindow + entry point
  5. Data stores (settings, sessions)
"""
import sys, os, re, json, math, time, random, threading
import numpy as np
import sounddevice as sd
import keyboard
import pyperclip
from faster_whisper import WhisperModel

from PyQt6.QtCore import (Qt, QObject, QTimer, QSize, QPointF, QRectF, pyqtSignal,
                          QVariantAnimation, QPropertyAnimation, QEasingCurve)
from PyQt6.QtGui import (QColor, QPainter, QPainterPath, QLinearGradient, QRadialGradient, QGradient,
                         QPen, QBrush, QFont, QFontMetrics, QIcon, QPixmap, QShortcut, QKeySequence, QTextCursor)
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout,
                             QStackedWidget, QScrollArea, QPushButton, QAbstractButton, QLineEdit, QTextEdit,
                             QComboBox, QSlider, QGraphicsDropShadowEffect, QGraphicsOpacityEffect,
                             QFileDialog, QMessageBox, QSizePolicy)

# ============================================================================ 1. CONFIG & HELPERS
SAMPLE_RATE = 16000
ROLLING_SECONDS = 3          # rolling buffer used for the "Hey Faster" wake phrase
STOP_CHECK_SECONDS = 4       # rolling buffer used for the "stop writing" phrase + live captions
HOME = os.path.expanduser("~")
SESSIONS_FILE = os.path.join(HOME, ".faster_sessions.json")   # same file the old version used
SETTINGS_FILE = os.path.join(HOME, ".faster_settings.json")
UI_FONT = "Segoe UI"
MODELS = ["tiny", "base", "small", "medium"]
LANGUAGES = [("Auto-detect", "auto"), ("English", "en"), ("Arabic", "ar"), ("Spanish", "es"), ("French", "fr"),
             ("German", "de"), ("Hindi", "hi"), ("Urdu", "ur"), ("Turkish", "tr"), ("Portuguese", "pt"),
             ("Russian", "ru"), ("Japanese", "ja"), ("Chinese", "zh")]
DEFAULTS = dict(accent="Cyan Pulse", model="base", language="auto", beam=5, device=-1,
                auto_paste=True, append=False, remove_fillers=False, voice_format=False,
                voice_cmds=True, live_caption=True, sound_cues=True, animated_bg=True,
                glow=100, on_top=False, hk_start="ctrl+1", hk_stop="ctrl+2")

def resource_path(rel):
    """Path helper that also works inside a PyInstaller exe."""
    try:
        base = sys._MEIPASS
    except Exception:
        base = os.path.abspath(".")
    return os.path.join(base, rel)

def qc(c, a=255):
    """QColor with alpha."""
    x = QColor(c)
    x.setAlpha(int(max(0, min(255, a))))
    return x

def mix(c1, c2, t):
    """Linear blend of two colours (alpha included)."""
    a, b, t = QColor(c1), QColor(c2), max(0.0, min(1.0, t))
    return QColor(*(int(x + (y - x) * t) for x, y in ((a.red(), b.red()), (a.green(), b.green()),
                                                       (a.blue(), b.blue()), (a.alpha(), b.alpha()))))

def font(size=10, weight=QFont.Weight.Normal, spacing=0.0, family=UI_FONT):
    f = QFont(family)
    f.setPointSizeF(size)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f

# ============================================================================ 2. THEME + QSS
ACCENTS = {  # name -> (primary, secondary)
    "Cyan Pulse":   ("#00E5FF", "#7C4DFF"),
    "Neon Orchid":  ("#C26BFF", "#FF3CAC"),
    "Emerald Grid": ("#10F5A8", "#00B7FF"),
    "Solar Flare":  ("#FF4D8D", "#FFB14A"),
}

class T:
    """Global theme. Painted widgets read from here at paint time, so changing accent just repaints."""
    BG, TEXT, MUTED, DANGER, WARN = "#06060D", "#F2F4FF", "#8A8FB5", "#FF4D6D", "#FFC857"
    name = "Cyan Pulse"
    c1, c2 = QColor(ACCENTS[name][0]), QColor(ACCENTS[name][1])
    glow = 1.0   # global glow multiplier (0..1), user adjustable

    @classmethod
    def set_accent(cls, name):
        name = name if name in ACCENTS else "Cyan Pulse"
        cls.name, cls.c1, cls.c2 = name, QColor(ACCENTS[name][0]), QColor(ACCENTS[name][1])

def build_qss():
    c1, c2 = T.c1.name(), T.c2.name()
    return f"""
    QLabel {{ color:{T.TEXT}; background:transparent; }}
    QToolTip {{ background:#10101C; color:{T.TEXT}; border:1px solid {c1}; padding:6px 10px; border-radius:6px; }}
    QTextEdit {{ background:transparent; border:none; color:{T.TEXT}; selection-background-color:{c1}; selection-color:#06060D; }}
    QLineEdit {{ background:rgba(255,255,255,10); border:1px solid rgba(255,255,255,24); border-radius:12px;
                padding:8px 14px; color:{T.TEXT}; selection-background-color:{c1}; selection-color:#06060D; }}
    QLineEdit:focus {{ border:1px solid {c1}; background:rgba(255,255,255,16); }}
    QLineEdit#title {{ background:transparent; border:none; border-bottom:1px solid transparent; border-radius:0;
                      padding:2px 0; font-size:16px; font-weight:700; }}
    QLineEdit#title:focus {{ border-bottom:1px solid {c1}; }}
    QComboBox {{ background:rgba(255,255,255,10); border:1px solid rgba(255,255,255,24); border-radius:10px;
                padding:7px 12px; color:{T.TEXT}; min-width:170px; }}
    QComboBox:hover, QComboBox:focus {{ border:1px solid {c1}; }}
    QComboBox::drop-down {{ border:none; width:26px; }}
    QComboBox QAbstractItemView {{ background:#0E0E1A; color:{T.TEXT}; border:1px solid {c1}; outline:none;
                                  selection-background-color:rgba(124,77,255,90); padding:4px; }}
    QScrollBar:vertical {{ background:transparent; width:10px; margin:2px; }}
    QScrollBar::handle:vertical {{ background:rgba(255,255,255,36); border-radius:4px; min-height:30px; }}
    QScrollBar::handle:vertical:hover {{ background:{c1}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
    QSlider::groove:horizontal {{ height:4px; background:rgba(255,255,255,30); border-radius:2px; }}
    QSlider::sub-page:horizontal {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 {c1},stop:1 {c2}); border-radius:2px; }}
    QSlider::handle:horizontal {{ background:#FFFFFF; width:16px; height:16px; margin:-6px 0; border-radius:8px; border:2px solid {c1}; }}
    QMessageBox, QFileDialog {{ background:#0E0E1A; }}
    QMessageBox QLabel {{ color:{T.TEXT}; }}
    QMessageBox QPushButton {{ background:rgba(255,255,255,12); color:{T.TEXT}; border:1px solid {c1};
                              border-radius:8px; padding:6px 18px; min-width:70px; }}
    QMessageBox QPushButton:hover {{ background:{c1}; color:#06060D; }}
    """

# ============================================================================ 3. ANIMATION UTILITIES
def make_anim(parent, cb, duration=200, curve=QEasingCurve.Type.OutCubic):
    a = QVariantAnimation(parent)
    a.setDuration(duration)
    a.setEasingCurve(curve)
    a.valueChanged.connect(cb)
    return a

def run_anim(a, start, end):
    a.stop()
    a.setStartValue(float(start))
    a.setEndValue(float(end))
    a.start()

def fade_in(widget, duration=320):
    """Fade a widget in, then drop the effect so it costs nothing afterwards."""
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", widget)
    a.setDuration(duration)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    a.finished.connect(lambda: widget.setGraphicsEffect(None))
    a.start()
    widget._fade = a

# ============================================================================ 4. PAINTED NEON WIDGETS
class Backdrop(QWidget):
    """Window background: deep black, slow-drifting neon glow blobs and a faint cyber grid."""
    def __init__(self):
        super().__init__()
        self.t, self.animated = 0.0, True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(66)

    def _tick(self):
        if self.animated:
            self.t += 0.014
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.BG))
        w, h, t = self.width(), self.height(), self.t
        blobs = [(0.12 + 0.10 * math.sin(t * 1.1), 0.18 + 0.10 * math.cos(t * 0.9), 0.60, T.c1, 54),
                 (0.88 + 0.08 * math.cos(t * 0.8), 0.85 + 0.08 * math.sin(t * 1.2), 0.55, T.c2, 58),
                 (0.55 + 0.12 * math.sin(t * 0.6), 0.45 + 0.12 * math.cos(t * 0.7), 0.35, mix(T.c1, T.c2, 0.5), 22)]
        for cx, cy, r, col, a in blobs:
            g = QRadialGradient(QPointF(cx * w, cy * h), r * max(w, h))
            g.setColorAt(0, qc(col, a * T.glow))
            g.setColorAt(1, qc(col, 0))
            p.fillRect(self.rect(), QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 7), 1))
        for x in range(0, w, 56):
            p.drawLine(x, 0, x, h)
        for y in range(0, h, 56):
            p.drawLine(0, y, w, y)


class GlassCard(QFrame):
    """Glassmorphism card: translucent fill, gradient hairline border and a painted neon glow halo.
    Put content into `card.body` (a QVBoxLayout). `pulse` (0..1) drives the glow from outside."""
    M = 14   # transparent margin reserved for the glow halo

    def __init__(self, radius=22, pad=(28, 24), glow=True, parent=None):
        super().__init__(parent)
        self.radius, self.glow, self.pulse, self.tint, self._hover = radius, glow, 0.0, None, 0.0
        self._anim = make_anim(self, self._set_hover, 260)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.M, self.M, self.M, self.M)
        outer.setSpacing(0)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(pad[0], pad[1], pad[0], pad[1])
        self.body.setSpacing(10)
        outer.addLayout(self.body)

    def _set_hover(self, v):
        self._hover = v
        self.update()

    def enterEvent(self, e):
        run_anim(self._anim, self._hover, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        run_anim(self._anim, self._hover, 0.0)
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m = self.M
        r = QRectF(self.rect()).adjusted(m, m, -m, -m)
        tint = self.tint or T.c1
        energy = (max(self._hover * 0.55, self.pulse) * T.glow) if self.glow else 0.0
        if energy > 0.01:                                   # glow halo
            p.setBrush(Qt.BrushStyle.NoBrush)
            for i in range(m, 0, -1):
                k = 1 - i / m
                p.setPen(QPen(qc(tint, 80 * energy * k * k), 1.4))
                p.drawRoundedRect(r.adjusted(-i, -i, i, i), self.radius + i, self.radius + i)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(12, 12, 26, 150))                 # glass body
        p.drawRoundedRect(r, self.radius, self.radius)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, qc("#FFFFFF", 20))
        g.setColorAt(1, qc("#FFFFFF", 4))
        p.setBrush(g)
        p.drawRoundedRect(r, self.radius, self.radius)
        p.setPen(QPen(qc("#FFFFFF", 46), 1))                # top specular highlight
        p.drawLine(QPointF(r.left() + self.radius, r.top() + 0.5), QPointF(r.right() - self.radius, r.top() + 0.5))
        bg = QLinearGradient(r.topLeft(), r.bottomRight())  # gradient border
        e2 = min(1.0, energy * 1.3)
        bg.setColorAt(0, mix(qc("#FFFFFF", 44), qc(tint, 210), e2))
        bg.setColorAt(1, mix(qc("#FFFFFF", 16), qc(T.c2, 170), e2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QBrush(bg), 1.2))
        p.drawRoundedRect(r, self.radius, self.radius)


class NeonButton(QPushButton):
    """Painted button with hover glow + press feedback.
    kind: primary (gradient) | danger | ghost (glass) | ghostdanger"""
    def __init__(self, text="", kind="primary", compact=False, pill=False, parent=None):
        super().__init__(text, parent)
        self.kind, self.compact, self.pill, self._h = kind, compact, pill, 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(34 if compact else 48)
        self.setFont(font(9.5 if compact else 11.5, QFont.Weight.DemiBold))
        self.fx = QGraphicsDropShadowEffect(self)
        self.fx.setOffset(0, 0)
        self.setGraphicsEffect(self.fx)
        self._anim = make_anim(self, self._set_h, 220)
        self._sync_fx()

    def set_kind(self, kind):
        self.kind = kind
        self._sync_fx()
        self.update()

    def _glow_color(self):
        return QColor(T.DANGER) if self.kind in ("danger", "ghostdanger") else QColor(T.c1)

    def _sync_fx(self):
        base = 14 if self.kind in ("primary", "danger") else 0
        c = self._glow_color()
        c.setAlpha(int(210 * T.glow))
        self.fx.setColor(c)
        self.fx.setBlurRadius((base + 26 * self._h) * T.glow)

    def _set_h(self, v):
        self._h = v
        self._sync_fx()
        self.update()

    def enterEvent(self, e):
        run_anim(self._anim, self._h, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        run_anim(self._anim, self._h, 0.0)
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.isDown():
            r = r.adjusted(1.5, 1.5, -1.5, -1.5)
        rad = r.height() / 2 if self.pill else 11
        h = self._h
        if self.kind in ("primary", "danger"):
            a, b = (T.c1, T.c2) if self.kind == "primary" else (QColor(T.DANGER), QColor("#FF8E53"))
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, mix(a, "#FFFFFF", 0.20 * h))
            g.setColorAt(1, mix(b, "#FFFFFF", 0.20 * h))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r, rad, rad)
            txt = QColor("#06060D") if self.kind == "primary" else QColor("#FFFFFF")
        else:
            acc = QColor(T.DANGER) if self.kind == "ghostdanger" else T.c1
            p.setBrush(qc("#FFFFFF", 10 + 24 * h))
            p.setPen(QPen(qc(acc, 55 + 170 * h), 1.1))
            p.drawRoundedRect(r, rad, rad)
            txt = mix(T.TEXT, acc, h)
        p.setPen(txt)
        p.setFont(self.font())
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self.text())


class NavButton(QAbstractButton):
    """Sidebar item with animated active state and a glowing indicator bar."""
    def __init__(self, icon, text, checkable=True):
        super().__init__()
        self.icon_txt, self.label, self.badge = icon, text, ""
        self._a = self._h = 0.0
        self.setCheckable(checkable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(46)
        self._anim_a = make_anim(self, self._set_a, 280)
        self._anim_h = make_anim(self, self._set_h, 180)
        self.toggled.connect(lambda c: run_anim(self._anim_a, self._a, 1.0 if c else 0.0))

    def nextCheckState(self):    # the window decides who is active, not the click
        pass

    def _set_a(self, v):
        self._a = v
        self.update()

    def _set_h(self, v):
        self._h = v
        self.update()

    def enterEvent(self, e):
        run_anim(self._anim_h, self._h, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        run_anim(self._anim_h, self._h, 0.0)
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        a, h = self._a, self._h
        p.setPen(Qt.PenStyle.NoPen)
        if a > 0.01 or h > 0.01:
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, qc(T.c1, 48 * a + 16 * h))
            g.setColorAt(1, qc(T.c2, 14 * a + 6 * h))
            p.setBrush(g)
            p.drawRoundedRect(r, 12, 12)
        if a > 0.01:
            bar = QRectF(r.left() - 2, r.center().y() - 11 * a, 4, 22 * a)
            for i in range(6, 0, -1):
                p.setBrush(qc(T.c1, 18 * a * T.glow * (1 - i / 7)))
                p.drawRoundedRect(bar.adjusted(-i, -i, i, i), 2 + i, 2 + i)
            p.setBrush(T.c1)
            p.drawRoundedRect(bar, 2, 2)
        col = mix(mix(T.MUTED, T.TEXT, h), T.c1, a)
        p.setPen(col)
        p.setFont(font(12))
        p.drawText(QRectF(r.left() + 16, r.top(), 30, r.height()), Qt.AlignmentFlag.AlignVCenter, self.icon_txt)
        p.setFont(font(10.5, QFont.Weight.DemiBold if a > 0.5 else QFont.Weight.Normal))
        p.drawText(QRectF(r.left() + 52, r.top(), r.width() - 90, r.height()), Qt.AlignmentFlag.AlignVCenter, self.label)
        if self.badge:
            bw = 26
            br = QRectF(r.right() - bw - 10, r.center().y() - 10, bw, 20)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(qc(T.c1, 40 + 40 * a))
            p.drawRoundedRect(br, 10, 10)
            p.setPen(T.c1)
            p.setFont(font(8.5, QFont.Weight.Bold))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, self.badge)


class NeonSwitch(QAbstractButton):
    """Animated toggle with neon knob."""
    def __init__(self, checked=False):
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(52, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._x = 1.0 if checked else 0.0
        self.setChecked(checked)
        self._anim = make_anim(self, self._set_x, 220)
        self.toggled.connect(lambda c: run_anim(self._anim, self._x, 1.0 if c else 0.0))

    def _set_x(self, v):
        self._x = v
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r, x = QRectF(2, 3, self.width() - 4, self.height() - 6), self._x
        off = qc("#FFFFFF", 30)
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, mix(off, T.c1, x))
        g.setColorAt(1, mix(off, T.c2, x))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        c = QPointF(r.left() + 3 + d / 2 + x * (r.width() - d - 6), r.center().y())
        if x > 0.02:
            for i in (9, 6, 3):
                p.setBrush(qc(T.c1, 26 * x * T.glow))
                p.drawEllipse(c, d / 2 + i / 1.4, d / 2 + i / 1.4)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(c, d / 2, d / 2)


class AccentSwatch(QAbstractButton):
    """Round accent-colour picker."""
    def __init__(self, name):
        super().__init__()
        self.name = name
        self.setFixedSize(46, 46)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(name)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        a, b = ACCENTS[self.name]
        c = QPointF(self.width() / 2, self.height() / 2)
        sel = (T.name == self.name)
        if sel or self.underMouse():
            p.setPen(Qt.PenStyle.NoPen)
            for i in (8, 5, 2):
                p.setBrush(qc(a, 30))
                p.drawEllipse(c, 14 + i, 14 + i)
        g = QLinearGradient(QPointF(10, 10), QPointF(36, 36))
        g.setColorAt(0, QColor(a))
        g.setColorAt(1, QColor(b))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, 13, 13)
        if sel:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#FFFFFF"), 2))
            p.drawEllipse(c, 19, 19)


class GradientLabel(QWidget):
    """Text filled with a (gently shimmering) accent gradient."""
    def __init__(self, text, size=12, weight=QFont.Weight.Bold, spacing=0.0, parent=None):
        super().__init__(parent)
        self._text, self._font, self.phase = text, font(size, weight, spacing), 0.0
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._fit()

    def _fit(self):
        fm = QFontMetrics(self._font)
        self.setFixedHeight(fm.height() + 4)
        self._w = fm.horizontalAdvance(self._text) + 6
        self.setMinimumWidth(self._w)
        self.updateGeometry()

    def setText(self, t):
        self._text = t
        self._fit()
        self.update()

    def sizeHint(self):
        return QSize(self._w, self.height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fm = QFontMetrics(self._font)
        path = QPainterPath()
        path.addText(0, fm.ascent() + 2, self._font, self._text)
        w = max(self._w, 1)
        s = w * 0.6 * math.sin(self.phase)
        g = QLinearGradient(s, 0, s + w, 0)
        g.setSpread(QGradient.Spread.ReflectSpread)
        g.setColorAt(0, T.c1)
        g.setColorAt(1, T.c2)
        p.fillPath(path, QBrush(g))


class Divider(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(1)

    def paintEvent(self, e):
        QPainter(self).fillRect(self.rect(), qc("#FFFFFF", 14))


class StatusPill(QWidget):
    """Glass pill with a pulsing status dot."""
    def __init__(self, compact=False):
        super().__init__()
        self.compact, self.text, self.state, self.pulse = compact, "", "loading", 0.0
        self.setFont(font(8.5 if compact else 9.5, QFont.Weight.DemiBold))
        self.setFixedHeight(26 if compact else 34)

    def color(self):
        return QColor({"recording": T.DANGER, "error": T.DANGER, "transcribing": T.WARN,
                       "loading": T.WARN}.get(self.state, T.c1.name()))

    def set(self, text, state):
        self.text, self.state = text, state
        self.setFixedWidth(QFontMetrics(self.font()).horizontalAdvance(text) + (36 if self.compact else 48))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col, r = self.color(), QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(qc(col, 22))
        p.setPen(QPen(qc(col, 95), 1))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        c = QPointF(r.left() + 15, r.center().y())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(col, 70 * (1 - self.pulse)))
        p.drawEllipse(c, 4 + 5 * self.pulse, 4 + 5 * self.pulse)
        p.setBrush(col)
        p.drawEllipse(c, 3.6, 3.6)
        p.setPen(mix(col, "#FFFFFF", 0.35))
        p.setFont(self.font())
        p.drawText(QRectF(r.left() + 28, r.top(), r.width() - 30, r.height()), Qt.AlignmentFlag.AlignVCenter, self.text)


class LogoMark(QWidget):
    """Fallback logo (used when logo.png is missing): animated mini equaliser in a glass tile."""
    def __init__(self, size=40):
        super().__init__()
        self.setFixedSize(size, size)
        self.phase = 0.0

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, qc(T.c1, 70))
        g.setColorAt(1, qc(T.c2, 70))
        p.setBrush(g)
        p.setPen(QPen(qc(T.c1, 150), 1))
        p.drawRoundedRect(r, 11, 11)
        cy, n = r.center().y(), 5
        for i in range(n):
            hgt = 5 + 13 * (math.sin(self.phase + i * 0.9) * 0.5 + 0.5)
            x = r.left() + 9 + i * ((r.width() - 18) / (n - 1))
            p.setPen(QPen(mix(T.c1, T.c2, i / (n - 1)), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x, cy - hgt / 2), QPointF(x, cy + hgt / 2))


class WaveWidget(QWidget):
    """Neon equaliser. Modes: idle (breathing) | recording (live level) | transcribing (scanner sweep)."""
    MAXN = 100

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(150)
        self.mode, self.t = "idle", 0.0
        self.cur, self.peak = [0.0] * self.MAXN, [0.0] * self.MAXN

    def _n(self):
        return max(24, min(self.MAXN, int(self.width() / 11)))

    def tick(self, dt, level, mode):
        self.mode, self.t = mode, self.t + dt * 2.4
        n, t = self._n(), self.t
        for i in range(n):
            if mode == "recording":
                tgt = min(level * random.uniform(0.5, 1.2) * (math.sin(i * 0.4 + t * 2) * 0.3 + 0.7), 1.0)
            elif mode == "transcribing":
                d = i / n - ((t * 0.5) % 1.3 - 0.15)
                tgt = 0.10 + 0.80 * math.exp(-(d * 9) ** 2)
            else:
                tgt = (math.sin(i * 0.3 + t) * 0.5 + 0.5) * 0.15 + 0.03
            self.cur[i] += (tgt - self.cur[i]) * 0.3
            self.peak[i] = max(self.peak[i] - 0.012, self.cur[i])
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, n = self.width(), self.height(), self._n()
        step, cy, active = w / n, h / 2, self.mode != "idle"
        bw = min(6.0, step * 0.55)
        bl = QLinearGradient(0, 0, w, 0)
        bl.setColorAt(0, qc(T.c1, 0))
        bl.setColorAt(0.5, qc(T.c1, 60))
        bl.setColorAt(1, qc(T.c2, 0))
        p.setPen(QPen(QBrush(bl), 1))
        p.drawLine(QPointF(0, cy), QPointF(w, cy))
        for pass_ in ((0, 1) if active else (1,)):          # pass 0 = glow, pass 1 = core
            for i in range(n):
                x, hh = step * (i + 0.5), max(4.0, self.cur[i] * (h - 24)) / 2
                col = mix(T.c1, T.c2, i / max(n - 1, 1))
                if pass_ == 0:
                    p.setPen(QPen(qc(col, 34 * T.glow), bw + 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                else:
                    p.setPen(QPen(col, bw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(x, cy - hh), QPointF(x, cy + hh))
        if self.mode == "recording":                         # falling peak dots
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(n):
                x, ph = step * (i + 0.5), self.peak[i] * (h - 24) / 2 + 7
                p.setBrush(qc(mix(T.c1, T.c2, i / max(n - 1, 1)), 130))
                p.drawEllipse(QPointF(x, cy - ph), 1.6, 1.6)
                p.drawEllipse(QPointF(x, cy + ph), 1.6, 1.6)


class StatCard(GlassCard):
    """Compact KPI tile with a count-up animation, painted directly (no child widgets)."""
    def __init__(self, title, suffix="", icon=""):
        super().__init__(radius=18, pad=(20, 14))
        self.title, self.suffix, self.icon, self._v = title, suffix, icon, 0.0
        self._count = make_anim(self, self._set_v, 900)
        self.setFixedHeight(112 + 2 * self.M)

    def _set_v(self, v):
        self._v = v
        self.update()

    def set_value(self, v):
        run_anim(self._count, self._v, v)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        m, x0 = self.M, self.M + 22
        p.setPen(QColor(T.MUTED))
        p.setFont(font(8.5, QFont.Weight.Bold, 1.6))
        p.drawText(QPointF(x0, m + 32), self.title)
        val, vf = str(int(round(self._v))), font(26, QFont.Weight.Bold)
        path = QPainterPath()
        path.addText(x0, m + 78, vf, val)
        g = QLinearGradient(x0, 0, x0 + 120, 0)
        g.setColorAt(0, T.c1)
        g.setColorAt(1, T.c2)
        p.fillPath(path, QBrush(g))
        if self.suffix:
            p.setPen(QColor(T.MUTED))
            p.setFont(font(10))
            p.drawText(QPointF(x0 + QFontMetrics(vf).horizontalAdvance(val) + 8, m + 78), self.suffix)
        p.setPen(qc("#FFFFFF", 70))
        p.setFont(font(22))
        p.drawText(QRectF(self.width() - m - 70, m, 50, 70), Qt.AlignmentFlag.AlignCenter, self.icon)


class Toast(QWidget):
    """Slide-up glass notification, bottom-right of the window."""
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.msg, self._v = "", 0.0
        self._anim = make_anim(self, self._set_v, 340)
        self._anim.finished.connect(lambda: self._v <= 0.01 and self.hide())
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: run_anim(self._anim, self._v, 0.0))
        self.setFont(font(10.5, QFont.Weight.DemiBold))
        self.hide()

    def popup(self, msg):
        self.msg = msg
        self.resize(QFontMetrics(self.font()).horizontalAdvance(msg) + 66, 50)
        self.show()
        self.raise_()
        self._timer.stop()
        run_anim(self._anim, self._v, 1.0)
        self._timer.start(2200)

    def _set_v(self, v):
        self._v = v
        self.reposition()
        self.update()

    def reposition(self):
        par = self.parentWidget()
        if par:
            self.move(int(par.width() - self.width() - 28), int(par.height() - self.height() - 26 + (1 - self._v) * 34))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(max(0.0, min(1.0, self._v)))
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        for i in range(8, 0, -1):
            p.setPen(QPen(qc(T.c1, 22 * T.glow * (1 - i / 9) ** 2), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(-i / 2, -i / 2, i / 2, i / 2), 14 + i / 2, 14 + i / 2)
        p.setBrush(QColor(14, 14, 28, 238))
        p.setPen(QPen(qc(T.c1, 150), 1.1))
        p.drawRoundedRect(r, 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(T.c1)
        p.drawEllipse(QPointF(r.left() + 20, r.center().y()), 3.5, 3.5)
        p.setPen(QColor(T.TEXT))
        p.setFont(self.font())
        p.drawText(QRectF(r.left() + 34, r.top(), r.width() - 40, r.height()), Qt.AlignmentFlag.AlignVCenter, self.msg)


def safe_fade(w):
    """fade_in that ignores widgets deleted in the meantime."""
    try:
        if w.isVisible():
            fade_in(w, 300)
    except RuntimeError:
        pass

def lbl(text="", size=10, weight=QFont.Weight.Normal, color=None, spacing=0.0, wrap=False):
    l = QLabel(text)
    l.setFont(font(size, weight, spacing))
    l.setStyleSheet(f"color:{color or T.TEXT}; background:transparent;")
    l.setWordWrap(wrap)
    return l

def make_scroll(inner):
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QFrame.Shape.NoFrame)
    sc.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    sc.setWidget(inner)
    inner.setAutoFillBackground(False)
    sc.viewport().setAutoFillBackground(False)
    sc.setStyleSheet("QScrollArea{background:transparent;border:none;} QScrollArea > QWidget > QWidget{background:transparent;}")
    return sc

# ============================================================================ 5. DATA STORES
class Settings(QObject):
    """Persistent key/value settings. `changed(key)` fires only when a value really changes."""
    changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.data = dict(DEFAULTS)
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except Exception:
            pass

    def get(self, k):
        return self.data.get(k, DEFAULTS.get(k))

    def set(self, k, v):
        if self.data.get(k) == v:
            return
        self.data[k] = v
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass
        self.changed.emit(k)


class SessionStore(QObject):
    """Saved transcripts (same JSON file as before; new fields are optional)."""
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.items = []
        try:
            with open(SESSIONS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.items = [d for d in data if isinstance(d, dict) and "text" in d and "title" in d]
        except Exception:
            pass

    def _commit(self):
        try:
            with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.items, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        self.changed.emit()

    def add(self, title, text):
        self.items.append({"title": title, "text": text, "time": time.strftime("%H:%M"),
                           "date": time.strftime("%Y-%m-%d"), "pinned": False})
        self._commit()

    def remove(self, s):
        if s in self.items:
            self.items.remove(s)
            self._commit()

    def toggle_pin(self, s):
        s["pinned"] = not s.get("pinned", False)
        self._commit()

    def clear(self):
        self.items.clear()
        self._commit()

# ============================================================================ 6. ENGINE
FILLER_RE = re.compile(r"\b(?:um+|uh+|erm+|hmm+)\b[,.]?\s*", re.I)
NEWLINE_RE = re.compile(r"\s*\bnew (line|paragraph)\b[.,]?\s*", re.I)

class Engine(QObject):
    """Audio capture, whisper transcription, hotkeys and voice commands. Emits signals only —
    it never touches widgets, so it is safe to call from the audio/keyboard/worker threads."""
    state = pyqtSignal(str)               # idle | recording | transcribing | loading
    transcribed = pyqtSignal(str, float)  # text, seconds of audio
    live_text = pyqtSignal(str)
    model_state = pyqtSignal(str, str)    # loading | ready | error, model name
    notice = pyqtSignal(str)

    def __init__(self, settings):
        super().__init__()
        self.S = settings
        self.model, self.stream = None, None
        self.is_recording, self.paused = False, False
        self.recording, self.rolling, self.rec_rolling = [], [], []
        self.level, self.rec_t0 = 0.0, 0.0
        self.lock = threading.Lock()
        self._hk = []
        threading.Thread(target=self._listener, daemon=True).start()

    # ---- audio ----
    def start_stream(self):
        self.stop_stream()
        dev = int(self.S.get("device"))
        try:
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                                         device=None if dev < 0 else dev, callback=self._audio_cb)
            self.stream.start()
            return True
        except Exception as ex:
            self.notice.emit(f"Microphone error: {str(ex)[:70]}")
            return False

    def stop_stream(self):
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        except Exception:
            pass
        self.stream = None

    def _audio_cb(self, indata, frames, time_info, status):
        rms = float(np.sqrt(np.mean((indata.astype(np.float32) / 32768.0) ** 2)))   # normalised 0..1
        self.level = min(rms * 9.0, 1.0)
        self.rolling.append(indata.copy())
        total, mx = sum(len(c) for c in self.rolling), ROLLING_SECONDS * SAMPLE_RATE
        while total > mx and len(self.rolling) > 1:
            total -= len(self.rolling.pop(0))
        if self.is_recording:
            self.recording.append(indata.copy())
            self.rec_rolling.append(indata.copy())
            total, mx = sum(len(c) for c in self.rec_rolling), STOP_CHECK_SECONDS * SAMPLE_RATE
            while total > mx and len(self.rec_rolling) > 1:
                total -= len(self.rec_rolling.pop(0))

    # ---- model ----
    def load_model(self, size=None):
        size = size or self.S.get("model")
        self.model = None
        self.model_state.emit("loading", size)
        self.state.emit("loading")

        def work():
            try:
                m = WhisperModel(size, device="cpu", compute_type="int8")
            except Exception as ex:
                self.model_state.emit("error", size)
                self.notice.emit(f"Model error: {str(ex)[:70]}")
                return
            self.model = m
            self.model_state.emit("ready", size)
            self.state.emit("idle")
        threading.Thread(target=work, daemon=True).start()

    def transcribe(self, chunks, fast=False):
        m = self.model
        if not chunks or m is None:
            return ""
        audio = np.concatenate(chunks, axis=0).astype(np.float32).flatten() / 32768.0
        lang = self.S.get("language")
        with self.lock:
            segs, _ = m.transcribe(audio, beam_size=1 if fast else int(self.S.get("beam")),
                                   language=None if lang in ("", "auto") else lang)
            return " ".join(s.text for s in segs).strip()

    # ---- recording ----
    def start_recording(self):
        if self.paused or self.is_recording:
            return
        if self.model is None:
            self.notice.emit("Speech engine is still loading…")
            return
        self.recording, self.rec_rolling, self.rec_t0 = [], [], time.time()
        self.is_recording = True
        self.state.emit("recording")
        self.cue("start")

    def stop_recording(self):
        if not self.is_recording:
            return
        self.is_recording = False
        self.state.emit("transcribing")
        self.cue("stop")
        threading.Thread(target=self._process, daemon=True).start()

    def _process(self):
        chunks, self.recording = self.recording, []
        if not chunks:
            self.state.emit("idle")
            return
        dur = sum(len(c) for c in chunks) / SAMPLE_RATE
        text = self.clean(self.strip_stop_phrase(self.transcribe(chunks)))
        if text:
            try:
                pyperclip.copy(text)
                if self.S.get("auto_paste"):
                    time.sleep(0.1)
                    keyboard.send("ctrl+v")
            except Exception:
                pass
            self.transcribed.emit(text, dur)
        else:
            self.notice.emit("No speech detected")
        self.rolling = []
        self.state.emit("idle")

    @staticmethod
    def strip_stop_phrase(text):
        i = text.lower().rfind("stop writing")
        return text[:i].rstrip(" ,.") if i != -1 else text

    def clean(self, text):
        text = re.sub(r"^\W*hey,?\s+faster\W*", "", text, flags=re.I)      # drop the wake phrase itself
        if self.S.get("remove_fillers"):
            text = FILLER_RE.sub("", text)
        if self.S.get("voice_format"):
            text = NEWLINE_RE.sub(lambda m: "\n\n" if m.group(1).lower() == "paragraph" else "\n", text)
        return text.strip()

    def cue(self, kind):
        """Tiny synthesised start/stop beeps."""
        if not self.S.get("sound_cues"):
            return

        def play():
            try:
                sr, f = 22050, ((660, 880) if kind == "start" else (880, 520))
                t = np.linspace(0, 0.09, int(sr * 0.09), False)
                tone = np.concatenate([np.sin(2 * np.pi * x * t) * np.hanning(len(t)) for x in f]) * 0.16
                sd.play(tone.astype(np.float32), sr)
            except Exception:
                pass
        threading.Thread(target=play, daemon=True).start()

    # ---- wake phrase / stop phrase / live captions ----
    def _listener(self):
        while True:
            time.sleep(1.5)
            if self.paused or self.model is None:
                continue
            if not self.is_recording:
                if not self.S.get("voice_cmds"):
                    continue
                low = self.transcribe(list(self.rolling), fast=True).lower()
                if "hey" in low and "faster" in low:
                    self.start_recording()
            else:
                cmds, live = self.S.get("voice_cmds"), self.S.get("live_caption")
                if not (cmds or live):
                    continue
                text = self.transcribe(list(self.rec_rolling), fast=True)
                if live:
                    self.live_text.emit(text)
                if cmds and "stop" in text.lower() and "writing" in text.lower():
                    self.stop_recording()

    # ---- hotkeys ----
    def set_hotkeys(self, start, stop):
        self.clear_hotkeys()
        try:
            self._hk.append(keyboard.add_hotkey(start, self.start_recording))
            self._hk.append(keyboard.add_hotkey(stop, self.stop_recording))
            return True
        except Exception:
            self.clear_hotkeys()
            return False

    def clear_hotkeys(self):
        for h in self._hk:
            try:
                keyboard.remove_hotkey(h)
            except Exception:
                pass
        self._hk = []

    def shutdown(self):
        self.clear_hotkeys()
        self.stop_stream()
        try:
            keyboard.unhook_all()
        except Exception:
            pass

# ============================================================================ 7. PAGES
def pretty_hk(hk):
    return hk.replace("+", " + ")


class StudioPage(QWidget):
    """Live dictation: control card (waveform / record button) · KPI tiles · editable transcript."""
    def __init__(self, win):
        super().__init__()
        self.win, self.S = win, win.settings
        self._state, self._queue, self._chunk = "loading", [], 1
        self._typer = QTimer(self)
        self._typer.timeout.connect(self._type_step)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(40, 24, 40, 30)
        col.setSpacing(14)
        root.addWidget(make_scroll(inner))

        col.addWidget(GradientLabel("—  SPEECH TO TEXT  01", 9, QFont.Weight.Bold, 2.0))
        self.hero = GradientLabel("Speak. We'll keep up.", 30, QFont.Weight.Bold)
        col.addWidget(self.hero)
        col.addWidget(lbl("A clear space for fast, focused dictation.", 12, color=T.MUTED))
        col.addSpacing(6)

        # ---- control card ----
        self.card = GlassCard(radius=26, pad=(34, 28))
        col.addWidget(self.card)
        top = QHBoxLayout()
        self.state_lbl = lbl("●  LOADING ENGINE", 9, QFont.Weight.Bold, T.WARN, 2.0)
        self.timer_lbl = lbl("00:00", 13, QFont.Weight.Bold, T.MUTED)
        self.timer_lbl.setFont(font(13, QFont.Weight.Bold, family="Consolas"))
        top.addWidget(self.state_lbl)
        top.addStretch()
        top.addWidget(self.timer_lbl)
        self.card.body.addLayout(top)
        self.status_lbl = lbl("Warming up the speech engine…", 24, QFont.Weight.Bold)
        self.card.body.addWidget(self.status_lbl)
        self.card.body.addWidget(lbl("Start with a thought, a note, or the next thing you need to remember.", 10.5, color=T.MUTED))
        self.wave = WaveWidget()
        self.card.body.addWidget(self.wave)
        self.live = lbl("", 10.5, color=T.MUTED)
        f = self.live.font()
        f.setItalic(True)
        self.live.setFont(f)
        self.live.setMinimumHeight(22)
        self.card.body.addWidget(self.live)

        ctl = QHBoxLayout()
        ctl.setSpacing(16)
        self.rec_btn = NeonButton("🎤  Start listening", "primary", pill=True)
        self.rec_btn.setMinimumWidth(240)
        self.rec_btn.clicked.connect(self._toggle_record)
        self.hk_lbl = lbl("", 10, color=T.MUTED)
        ctl.addWidget(self.rec_btn)
        ctl.addWidget(self.hk_lbl)
        ctl.addStretch()
        ctl.addWidget(lbl("Auto-paste", 10, color=T.MUTED))
        self.paste_sw = NeonSwitch(self.S.get("auto_paste"))
        self.paste_sw.toggled.connect(lambda c: self.S.set("auto_paste", c))
        ctl.addWidget(self.paste_sw)
        self.card.body.addLayout(ctl)

        # ---- KPI tiles ----
        stats = QHBoxLayout()
        stats.setSpacing(0)
        self.st_words = StatCard("WORDS IN TRANSCRIPT", "", "✍")
        self.st_pace = StatCard("LAST SPEAKING PACE", "wpm", "⚡")
        self.st_saved = StatCard("SAVED SESSIONS", "", "🗂")
        for s in (self.st_words, self.st_pace, self.st_saved):
            stats.addWidget(s)
        col.addLayout(stats)
        self.st_saved.set_value(len(win.store.items))

        # ---- transcript ----
        col.addWidget(GradientLabel("—  YOUR TRANSCRIPT  02", 9, QFont.Weight.Bold, 2.0))
        self.tcard = GlassCard(radius=26, pad=(30, 24))
        col.addWidget(self.tcard)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(lbl("SESSION TITLE", 8.5, QFont.Weight.Bold, T.MUTED, 1.5))
        self.title_edit = QLineEdit()
        self.title_edit.setObjectName("title")
        self.title_edit.setPlaceholderText("Untitled voice note")
        self.title_edit.setMinimumWidth(240)
        head.addWidget(self.title_edit)
        head.addStretch()
        self.count_lbl = lbl("0 words", 10, color=T.MUTED)
        head.addWidget(self.count_lbl)
        head.addSpacing(8)
        for text, cb, kind in (("📋  Copy", self.copy, "ghost"), ("💾  Save", self.save_clicked, "ghost"),
                               ("⬇  Export", self.export, "ghost"), ("🗑  Clear", self.clear_clicked, "ghostdanger")):
            b = NeonButton(text, kind, compact=True)
            b.setMinimumWidth(88)
            b.clicked.connect(cb)
            head.addWidget(b)
        self.tcard.body.addLayout(head)
        self.edit = QTextEdit()
        self.edit.setFont(font(12))
        self.edit.setPlaceholderText("Your transcript will appear here. You can also type or edit text directly.")
        self.edit.setMinimumHeight(210)
        self.edit.textChanged.connect(self._count)
        self.tcard.body.addWidget(self.edit)
        foot = lbl("FASTER  ·  100% Local & Free  ·  F11 fullscreen  ·  Esc to exit fullscreen", 8.5, color=T.MUTED)
        col.addWidget(foot)
        col.addStretch()
        self.set_hotkeys(self.S.get("hk_start"))
        self.S.changed.connect(self._on_setting)

    def _on_setting(self, k):
        if k == "auto_paste" and self.paste_sw.isChecked() != self.S.get(k):
            self.paste_sw.blockSignals(True)
            self.paste_sw.setChecked(self.S.get(k))
            self.paste_sw._x = 1.0 if self.S.get(k) else 0.0
            self.paste_sw.blockSignals(False)
            self.paste_sw.update()

    def set_hotkeys(self, start):
        self.hk_lbl.setText(pretty_hk(start))

    # ---- state ----
    def set_state(self, st):
        self._state = st
        names = {"idle": "READY FOR INPUT", "recording": "RECORDING", "transcribing": "TRANSCRIBING", "loading": "LOADING ENGINE"}
        msgs = {"idle": "Make room for a thought.", "recording": "Listening... Speak now.",
                "transcribing": "Transcribing your words...", "loading": "Warming up the speech engine…"}
        col = {"recording": T.DANGER, "transcribing": T.WARN, "loading": T.WARN}.get(st, T.c1.name())
        self.state_lbl.setText(f"●  {names[st]}")
        self.state_lbl.setStyleSheet(f"color:{col}; background:transparent;")
        self.status_lbl.setText(msgs[st])
        self.card.tint = QColor(T.DANGER) if st == "recording" else None
        if st != "recording":
            self.card.pulse = 0.0
            self.timer_lbl.setStyleSheet(f"color:{T.MUTED}; background:transparent;")
            self.live.setText("")
        else:
            self.timer_lbl.setStyleSheet(f"color:{T.DANGER}; background:transparent;")
        self.card.update()
        self.rec_btn.setEnabled(st in ("idle", "recording"))
        if st == "recording":
            self.rec_btn.setText("⏹  Stop listening")
            self.rec_btn.set_kind("danger")
        else:
            self.rec_btn.setText("🎤  Start listening")
            self.rec_btn.set_kind("primary")

    def refresh(self):
        self.set_state(self._state)

    def tick(self, dt, pulse, level):
        self.wave.tick(dt, level, self._state)
        if self._state == "recording":
            self.card.pulse = 0.35 + 0.65 * pulse
            self.card.update()
            el = int(time.time() - self.win.engine.rec_t0)
            self.timer_lbl.setText(f"{el // 60:02d}:{el % 60:02d}")
        elif self._state == "transcribing":
            self.card.pulse = 0.25 + 0.25 * pulse
            self.card.update()
        self.hero.phase = self.win.t * 0.5
        self.hero.update()

    def set_live(self, text):
        t = text.strip()
        self.live.setText(f"“…{t[-95:]}”" if t and self._state == "recording" else "")

    def _toggle_record(self):
        eng = self.win.engine
        eng.stop_recording() if eng.is_recording else eng.start_recording()

    # ---- transcript ----
    def current_text(self):
        return self.edit.toPlainText().strip()

    def _count(self):
        n = len(self.current_text().split()) if self.current_text() else 0
        self.count_lbl.setText(f"{n} word{'s' if n != 1 else ''}")
        if not self._typer.isActive():
            self.st_words.set_value(n)

    def show_result(self, text, dur):
        words = len(text.split())
        self.st_pace.set_value(min(400, round(words / max(dur / 60, 1 / 60))))
        self.type_text(text, self.S.get("append"))
        self.win.toast.popup("✓  Transcribed & pasted" if self.S.get("auto_paste") else "✓  Transcribed & copied")

    def type_text(self, text, append=False):
        """Typewriter reveal."""
        self._typer.stop()
        sep = ""
        if append and self.current_text():
            sep = "\n\n"
        else:
            self.edit.clear()
        self._queue = (sep + text).split(" ")
        self._chunk = max(1, len(self._queue) // 50)
        self._typer.start(25)

    def _type_step(self):
        if not self._queue:
            self._typer.stop()
            self._count()
            return
        part = " ".join(self._queue[:self._chunk])
        del self._queue[:self._chunk]
        cur = self.edit.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(part + (" " if self._queue else ""))
        self.edit.setTextCursor(cur)
        self.edit.ensureCursorVisible()

    def load_session(self, s):
        self._typer.stop()
        self.edit.setPlainText(s["text"])
        self.title_edit.setText(s["title"])

    def clear(self):
        self._typer.stop()
        self.edit.clear()
        self.title_edit.clear()

    def save_current(self):
        text = self.current_text()
        if not text:
            return False
        title = self.title_edit.text().strip() or text.split(".")[0][:45].strip() or "Untitled voice note"
        self.win.store.add(title, text)
        return True

    def copy(self):
        if self.current_text():
            pyperclip.copy(self.current_text())
            self.win.toast.popup("✓  Copied to clipboard")
        else:
            self.win.toast.popup("Nothing to copy yet")

    def save_clicked(self):
        self.win.toast.popup("✓  Saved to archive" if self.save_current() else "Nothing to save yet")

    def export(self):
        self.win.export_text(self.title_edit.text() or "transcript", self.current_text())

    def clear_clicked(self):
        self.clear()
        self.win.toast.popup("Transcript cleared")


class SessionRow(GlassCard):
    """One archive entry."""
    def __init__(self, win, s):
        super().__init__(radius=18, pad=(22, 14))
        left = QVBoxLayout()
        left.setSpacing(3)
        star = "★  " if s.get("pinned") else ""
        left.addWidget(lbl(star + s["title"], 11.5, QFont.Weight.Bold))
        prev = s["text"].replace("\n", " ")
        left.addWidget(lbl(prev[:110] + ("..." if len(prev) > 110 else ""), 9.5, color=T.MUTED))
        meta = f'{s.get("date", "")}  {s["time"]}  ·  {len(s["text"].split())} words'.strip()
        left.addWidget(lbl(meta, 8.5, color=T.MUTED))
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addLayout(left, 1)
        specs = [("Open", "ghost", 76, "Open in studio", lambda: win.open_session(s)),
                 ("📋", "ghost", 42, "Copy text", lambda: (pyperclip.copy(s["text"]), win.toast.popup("✓  Copied to clipboard"))),
                 ("☆" if not s.get("pinned") else "★", "ghost", 42, "Pin / unpin", lambda: win.store.toggle_pin(s)),
                 ("🗑", "ghostdanger", 42, "Delete", lambda: (win.store.remove(s), win.toast.popup("Session deleted")))]
        for text, kind, w, tip, cb in specs:
            b = NeonButton(text, kind, compact=True)
            b.setFixedWidth(w)
            b.setToolTip(tip)
            b.clicked.connect(cb)
            row.addWidget(b)
        self.body.addLayout(row)


class ArchivePage(QWidget):
    """Searchable, pinnable library of saved sessions."""
    def __init__(self, win):
        super().__init__()
        self.win = win
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        col = QVBoxLayout(inner)
        col.setContentsMargins(40, 24, 40, 30)
        col.setSpacing(14)
        root.addWidget(make_scroll(inner))
        col.addWidget(GradientLabel("—  YOUR LIBRARY  00", 9, QFont.Weight.Bold, 2.0))
        head = QHBoxLayout()
        head.addWidget(GradientLabel("Every thought, in order.", 28, QFont.Weight.Bold))
        head.addStretch()
        nb = NeonButton("＋  New session", "primary", compact=True)
        nb.setFixedHeight(40)
        nb.setMinimumWidth(150)
        nb.clicked.connect(win.new_session)
        head.addWidget(nb)
        col.addLayout(head)
        col.addWidget(lbl("Your saved transcripts, ready when you need them.", 12, color=T.MUTED))
        bar = QHBoxLayout()
        bar.setSpacing(12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Search titles and text…")
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.search, 1)
        bar.addWidget(lbl("Pinned only", 10, color=T.MUTED))
        self.pin_sw = NeonSwitch(False)
        self.pin_sw.toggled.connect(self.refresh)
        bar.addWidget(self.pin_sw)
        self.count = lbl("", 10, color=T.MUTED)
        bar.addWidget(self.count)
        col.addLayout(bar)
        self.list = QVBoxLayout()
        self.list.setSpacing(0)
        col.addLayout(self.list)
        col.addStretch()
        win.store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self, *_):
        while self.list.count():
            it = self.list.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        q, only_pin = self.search.text().strip().lower(), self.pin_sw.isChecked()
        items = [s for s in reversed(self.win.store.items)
                 if (not q or q in s["title"].lower() or q in s["text"].lower()) and (not only_pin or s.get("pinned"))]
        items.sort(key=lambda s: not s.get("pinned"))          # stable: pinned first, newest first inside groups
        self.count.setText(f"{len(items)} shown")
        if not items:
            box = QWidget()
            v = QVBoxLayout(box)
            v.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            v.setContentsMargins(0, 70, 0, 0)
            for w in (lbl("🕐", 34, color=T.MUTED), lbl("Your archive starts here." if not q else "No matches.", 16, QFont.Weight.Bold),
                      lbl("Finish a capture or save a transcript to keep it close." if not q else "Try a different search.", 10.5, color=T.MUTED)):
                w.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                v.addWidget(w)
            b = NeonButton("Start a new session  →", "ghost", compact=True)
            b.setMinimumWidth(200)
            b.clicked.connect(lambda: self.win.navigate("studio"))
            v.addSpacing(10)
            v.addWidget(b, 0, Qt.AlignmentFlag.AlignHCenter)
            self.list.addWidget(box)
            return
        for i, s in enumerate(items):
            row = SessionRow(self.win, s)
            self.list.addWidget(row)
            if i < 8:                                          # staggered entrance
                QTimer.singleShot(i * 55, lambda r=row: safe_fade(r))


class SettingRow(QWidget):
    def __init__(self, title, desc, control):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(lbl(title, 10.5, QFont.Weight.DemiBold))
        left.addWidget(lbl(desc, 9, color=T.MUTED, wrap=True))
        lay.addLayout(left, 1)
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class SettingsPage(QWidget):
    """Appearance · speech engine · behaviour · data · help."""
    def __init__(self, win):
        super().__init__()
        self.win, self.S, self.switches = win, win.settings, {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        self.col = QVBoxLayout(inner)
        self.col.setContentsMargins(40, 24, 40, 30)
        self.col.setSpacing(14)
        root.addWidget(make_scroll(inner))
        self.col.addWidget(GradientLabel("—  CONTROL ROOM  03", 9, QFont.Weight.Bold, 2.0))
        self.col.addWidget(GradientLabel("Make it yours.", 28, QFont.Weight.Bold))
        self.col.addWidget(lbl("Everything runs 100% locally on your PC. No internet, no cost.", 12, color=T.MUTED))

        # -- appearance --
        c = self.section("🎨", "APPEARANCE")
        sw = QHBoxLayout()
        sw.setSpacing(6)
        self.swatches = []
        for name in ACCENTS:
            b = AccentSwatch(name)
            b.clicked.connect(lambda _=False, n=name: self.S.set("accent", n))
            self.swatches.append(b)
            sw.addWidget(b)
        w = QWidget()
        w.setLayout(sw)
        self.row(c, "Neon accent", "Pick the glow palette. Applies instantly.", w)
        c.body.addWidget(Divider())
        self.row(c, "Animated background", "Drifting neon glow behind the interface. Turn off to save CPU.", self.switch("animated_bg"))
        c.body.addWidget(Divider())
        gl = QSlider(Qt.Orientation.Horizontal)
        gl.setRange(0, 100)
        gl.setValue(int(self.S.get("glow")))
        gl.setFixedWidth(220)
        gl.valueChanged.connect(lambda v: self.S.set("glow", v))
        self.row(c, "Glow intensity", "How strong the neon halos and shadows are.", gl)
        c.body.addWidget(Divider())
        self.row(c, "Always on top", "Keep Faster floating above other windows while you dictate.", self.switch("on_top"))

        # -- engine --
        c = self.section("🎛", "SPEECH ENGINE")
        self.model_cb = self.combo([(m.capitalize() + {"tiny": "  · fastest", "base": "  · balanced", "small": "  · accurate", "medium": "  · most accurate"}[m], m) for m in MODELS],
                                   self.S.get("model"), lambda v: self.S.set("model", v))
        self.row(c, "Model size", "Larger models are more accurate but slower. Downloaded on first use, then fully offline.", self.model_cb)
        c.body.addWidget(Divider())
        self.row(c, "Language", "Auto-detect, or lock a language for better accuracy.",
                 self.combo(LANGUAGES, self.S.get("language"), lambda v: self.S.set("language", v)))
        c.body.addWidget(Divider())
        self.dev_cb = self.combo(self.input_devices(), int(self.S.get("device")), lambda v: self.S.set("device", int(v)))
        self.row(c, "Microphone", "Input device used for dictation and wake phrase.", self.dev_cb)
        c.body.addWidget(Divider())
        beam_box = QHBoxLayout()
        self.beam_lbl = lbl(str(self.S.get("beam")), 10.5, QFont.Weight.Bold, T.MUTED)
        self.beam_lbl.setFixedWidth(20)
        bs = QSlider(Qt.Orientation.Horizontal)
        bs.setRange(1, 10)
        bs.setValue(int(self.S.get("beam")))
        bs.setFixedWidth(190)
        bs.valueChanged.connect(lambda v: (self.S.set("beam", v), self.beam_lbl.setText(str(v))))
        beam_box.addWidget(bs)
        beam_box.addWidget(self.beam_lbl)
        w = QWidget()
        w.setLayout(beam_box)
        self.row(c, "Accuracy (beam size)", "Higher = slightly better text, slightly slower.", w)
        c.body.addWidget(Divider())
        ap = NeonButton("Apply & reload engine", "primary", compact=True)
        ap.setMinimumWidth(190)
        ap.clicked.connect(win.reload_engine)
        self.row(c, "Apply changes", "Model and microphone changes take effect after a reload.", ap)

        # -- behaviour --
        c = self.section("⚡", "BEHAVIOUR")
        for key, title, desc in (
                ("auto_paste", "Auto-paste into the active app", "Types your words wherever your cursor is, the moment you stop."),
                ("append", "Append to transcript", "Add each dictation below the previous one instead of replacing it."),
                ("voice_cmds", "Hands-free voice commands", 'Say "Hey Faster" to start and "stop writing" to finish.'),
                ("live_caption", "Live captions", "Show a rolling preview of what you're saying while recording."),
                ("remove_fillers", "Remove filler words", 'Strips "um", "uh", "hmm" from the final text.'),
                ("voice_format", "Spoken formatting", 'Say "new line" or "new paragraph" to insert breaks.'),
                ("sound_cues", "Sound cues", "Short beeps when recording starts and stops.")):
            self.row(c, title, desc, self.switch(key))
            c.body.addWidget(Divider())
        self.hk_start, self.hk_stop = QLineEdit(self.S.get("hk_start")), QLineEdit(self.S.get("hk_stop"))
        for e in (self.hk_start, self.hk_stop):
            e.setFixedWidth(120)
        hk = QHBoxLayout()
        hk.setSpacing(8)
        hk.addWidget(lbl("Start", 9.5, color=T.MUTED))
        hk.addWidget(self.hk_start)
        hk.addWidget(lbl("Stop", 9.5, color=T.MUTED))
        hk.addWidget(self.hk_stop)
        ab = NeonButton("Apply", "ghost", compact=True)
        ab.setFixedWidth(80)
        ab.clicked.connect(self.apply_hk)
        hk.addWidget(ab)
        w = QWidget()
        w.setLayout(hk)
        self.row(c, "Global hotkeys", "Work from any app. Examples: ctrl+1, ctrl+alt+d, f9.", w)

        # -- data --
        c = self.section("🗂", "DATA")
        b1 = NeonButton("Export all (.md)", "ghost", compact=True)
        b1.setMinimumWidth(150)
        b1.clicked.connect(win.export_all)
        self.row(c, "Export archive", "Save every session into a single Markdown file.", b1)
        c.body.addWidget(Divider())
        b2 = NeonButton("Clear archive", "ghostdanger", compact=True)
        b2.setMinimumWidth(150)
        b2.clicked.connect(win.clear_archive)
        self.row(c, "Delete all sessions", "Permanently removes every saved session.", b2)

        # -- help --
        c = self.section("💡", "HOW FASTER WORKS")
        help_txt = ("•  Click inside any app (Notepad, Word, Chrome, Discord…) first, then start speaking.\n"
                    "•  Ctrl+1 starts, Ctrl+2 stops and pastes — or say “Hey Faster” / “stop writing”.\n"
                    "•  “New session” saves the current transcript to the archive and clears the board.\n"
                    "•  Click the session title to rename it. Pin ★ important sessions in the archive.\n"
                    "•  Shortcuts: F11 fullscreen · Ctrl+S save · Ctrl+N new session · Esc exits fullscreen.\n"
                    "•  Your voice never leaves your computer — transcription runs on an offline model.")
        c.body.addWidget(lbl(help_txt, 10, color=T.TEXT, wrap=True))
        self.col.addStretch()
        self.S.changed.connect(self._on_setting)

    # ---- builders ----
    def section(self, icon, title):
        card = GlassCard(radius=22, pad=(30, 22))
        card.body.addWidget(GradientLabel(f"{icon}  {title}", 9.5, QFont.Weight.Bold, 2.0))
        self.col.addWidget(card)
        return card

    def row(self, card, title, desc, control):
        card.body.addWidget(SettingRow(title, desc, control))

    def switch(self, key):
        s = NeonSwitch(bool(self.S.get(key)))
        s.toggled.connect(lambda c, k=key: self.S.set(k, c))
        self.switches[key] = s
        return s

    def combo(self, items, current, on_change):
        cb = QComboBox()
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        for text, data in items:
            cb.addItem(text, data)
        i = cb.findData(current)
        cb.setCurrentIndex(max(0, i))
        cb.currentIndexChanged.connect(lambda _: on_change(cb.currentData()))
        return cb

    @staticmethod
    def input_devices():
        items = [("System default", -1)]
        try:
            api = sd.query_devices(sd.default.device[0])["hostapi"]
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0 and d["hostapi"] == api:
                    items.append((d["name"][:42], i))
        except Exception:
            pass
        return items

    def apply_hk(self):
        a, b = self.hk_start.text().strip().lower(), self.hk_stop.text().strip().lower()
        try:
            keyboard.parse_hotkey(a)
            keyboard.parse_hotkey(b)
            if not a or not b or a == b:
                raise ValueError
        except Exception:
            self.win.toast.popup("Invalid hotkey combination")
            return
        self.S.set("hk_start", a)
        self.S.set("hk_stop", b)
        self.win.apply_hotkeys()
        self.win.toast.popup("✓  Hotkeys updated")

    def _on_setting(self, k):
        if k == "accent":
            for s in self.swatches:
                s.update()
        elif k in self.switches and self.switches[k].isChecked() != bool(self.S.get(k)):
            sw = self.switches[k]
            sw.blockSignals(True)
            sw.setChecked(bool(self.S.get(k)))
            sw._x = 1.0 if self.S.get(k) else 0.0
            sw.blockSignals(False)
            sw.update()

# ============================================================================ 8. CHROME
class Sidebar(QWidget):
    """Glass sidebar: logo, navigation, recent preview, engine status, shortcuts."""
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFixedWidth(264)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 26, 18, 20)
        lay.setSpacing(4)

        row = QHBoxLayout()
        row.setSpacing(12)
        pm = QPixmap(resource_path("logo.png"))
        self.logo = None
        if not pm.isNull():
            icon = QLabel()
            icon.setPixmap(pm.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        else:
            self.logo = icon = LogoMark()
        row.addWidget(icon)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(GradientLabel("FASTER.", 18, QFont.Weight.Bold))
        names.addWidget(lbl("VOICE WORKSPACE", 7.5, QFont.Weight.Bold, T.MUTED, 1.6))
        row.addLayout(names)
        row.addStretch()
        lay.addLayout(row)
        lay.addSpacing(30)
        lay.addWidget(lbl("WORKSPACE", 8, QFont.Weight.Bold, T.MUTED, 1.8))
        lay.addSpacing(6)

        self.nav = {}
        for key, icon_t, text, checkable in (("new", "＋", "New session", False), ("studio", "🎙", "Live studio", True),
                                             ("archive", "🕐", "Session archive", True), ("settings", "⚙", "Settings", True)):
            b = NavButton(icon_t, text, checkable)
            b.clicked.connect(win.new_session if key == "new" else (lambda _=False, k=key: win.navigate(k)))
            self.nav[key] = b
            lay.addWidget(b)

        lay.addSpacing(22)
        lay.addWidget(lbl("RECENT", 8, QFont.Weight.Bold, T.MUTED, 1.8))
        rc = GlassCard(radius=14, pad=(14, 11), glow=False)
        self.recent = lbl("Your saved sessions will\nappear here.", 9.5, color=T.MUTED, wrap=True)
        rc.body.addWidget(self.recent)
        lay.addWidget(rc)
        lay.addStretch()

        vc = GlassCard(radius=16, pad=(16, 13))
        vc.body.setSpacing(4)
        vc.body.addWidget(lbl("🎛  VOICE ENGINE", 8, QFont.Weight.Bold, T.MUTED, 1.4))
        self.model_lbl = lbl("Local whisper", 11.5, QFont.Weight.Bold)
        vc.body.addWidget(self.model_lbl)
        self.chip = StatusPill(compact=True)
        self.chip.set("LOADING", "loading")
        vc.body.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(vc)
        lay.addSpacing(8)
        self.sc1, self.sc2 = lbl("", 9, color=T.MUTED), lbl("", 9, color=T.MUTED)
        lay.addWidget(self.sc1)
        lay.addWidget(self.sc2)
        self.update_recent()

    def set_active(self, key):
        for k, b in self.nav.items():
            if b.isCheckable():
                b.setChecked(k == key)

    def set_hotkeys(self, a, b):
        self.sc1.setText(f"⌨  {pretty_hk(a)}   Start / resume")
        self.sc2.setText(f"⌨  {pretty_hk(b)}   Stop & save")

    def update_recent(self):
        items = self.win.store.items
        self.nav["archive"].badge = str(len(items)) if items else ""
        self.nav["archive"].update()
        if items:
            t = items[-1]["text"].replace("\n", " ")
            self.recent.setText(t[:60] + ("..." if len(t) > 60 else ""))
        else:
            self.recent.setText("Your saved sessions will\nappear here.")

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(8, 8, 18, 175))
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, qc(T.c1, 90))
        g.setColorAt(1, qc(T.c2, 30))
        p.setPen(QPen(QBrush(g), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())


class RoundButton(NeonButton):
    def __init__(self, glyph, tip):
        super().__init__(glyph, "ghost", compact=True, pill=True)
        self.setFixedSize(38, 38)
        self.setFont(font(12))
        self.setToolTip(tip)


class Topbar(QWidget):
    def __init__(self, win):
        super().__init__()
        self.setFixedHeight(72)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(40, 0, 32, 0)
        lay.setSpacing(14)
        self.crumb = lbl("FASTER  /  LIVE STUDIO", 9, QFont.Weight.Bold, T.MUTED, 1.6)
        self.pill = StatusPill()
        self.pill.set("Loading speech engine…", "loading")
        lay.addWidget(self.crumb)
        lay.addSpacing(14)
        lay.addWidget(self.pill)
        lay.addStretch()
        for glyph, tip, cb in (("🎨", "Cycle neon accent", win.cycle_accent), ("⛶", "Fullscreen (F11)", win.toggle_fullscreen),
                               ("⚙", "Settings", lambda: win.navigate("settings"))):
            b = RoundButton(glyph, tip)
            b.clicked.connect(cb)
            lay.addWidget(b)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(8, 8, 18, 120))
        g = QLinearGradient(0, 0, self.width(), 0)
        g.setColorAt(0, qc(T.c1, 70))
        g.setColorAt(1, qc(T.c2, 0))
        p.setPen(QPen(QBrush(g), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)

# ============================================================================ 9. MAIN WINDOW
def enable_dark_titlebar(win):
    """Windows 10/11: dark native title bar to match the theme (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        v = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(win.winId()), 20, ctypes.byref(v), ctypes.sizeof(v))
    except Exception:
        pass


class MainWindow(QMainWindow):
    TITLES = {"studio": "LIVE STUDIO", "archive": "SESSION ARCHIVE", "settings": "SETTINGS"}
    PAGES = ("studio", "archive", "settings")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Faster")
        self.resize(1280, 860)
        self.setMinimumSize(1000, 700)
        ico = resource_path("icon.ico")
        if os.path.exists(ico):
            self.setWindowIcon(QIcon(ico))

        self.settings = Settings()
        T.set_accent(self.settings.get("accent"))
        T.glow = int(self.settings.get("glow")) / 100
        QApplication.instance().setStyleSheet(build_qss())
        self.store, self.engine = SessionStore(), Engine(self.settings)
        self.t, self.is_full, self.state = 0.0, False, "loading"

        # ---- layout ----
        self.backdrop = Backdrop()
        self.backdrop.animated = bool(self.settings.get("animated_bg"))
        self.setCentralWidget(self.backdrop)
        root = QHBoxLayout(self.backdrop)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = Sidebar(self)
        root.addWidget(self.sidebar)
        right = QVBoxLayout()
        right.setSpacing(0)
        root.addLayout(right, 1)
        self.topbar = Topbar(self)
        right.addWidget(self.topbar)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.studio, self.archive, self.settings_page = StudioPage(self), ArchivePage(self), SettingsPage(self)
        for pg in (self.studio, self.archive, self.settings_page):
            self.stack.addWidget(pg)
        self.toast = Toast(self.backdrop)

        # ---- wiring ----
        e = self.engine
        e.state.connect(self.on_engine_state)
        e.transcribed.connect(self.studio.show_result)
        e.live_text.connect(self.studio.set_live)
        e.model_state.connect(self.on_model_state)
        e.notice.connect(self.toast.popup)
        self.settings.changed.connect(self.on_setting)
        self.store.changed.connect(self.on_store_changed)
        for seq, fn in (("F11", self.toggle_fullscreen), ("Esc", self.exit_fullscreen),
                        ("Ctrl+S", self.studio.save_clicked), ("Ctrl+N", self.new_session)):
            QShortcut(QKeySequence(seq), self, activated=fn)

        self.navigate("studio")
        self.apply_hotkeys()
        self.on_store_changed()
        self.engine.start_stream()
        self.engine.load_model()
        self.clock = QTimer(self)
        self.clock.timeout.connect(self.tick)
        self.clock.start(33)
        self.setWindowOpacity(0.0)
        self._open_anim = make_anim(self, self.setWindowOpacity, 600)
        run_anim(self._open_anim, 0.0, 1.0)

    # ---- frame loop ----
    def tick(self):
        self.t += 0.033
        pulse = (math.sin(self.t * 4.2) + 1) / 2
        for pill in (self.topbar.pill, self.sidebar.chip):
            pill.pulse = pulse
            pill.update()
        if self.sidebar.logo:
            self.sidebar.logo.phase = self.t * 3
            self.sidebar.logo.update()
        if self.stack.currentIndex() == 0:
            self.studio.tick(0.033, pulse, self.engine.level)

    # ---- navigation ----
    def navigate(self, key):
        idx = self.PAGES.index(key)
        if self.stack.currentIndex() != idx or not self.stack.currentWidget().isVisible():
            if key == "archive":
                self.archive.refresh()
            self.stack.setCurrentIndex(idx)
            fade_in(self.stack.currentWidget())
        self.sidebar.set_active(key)
        self.topbar.crumb.setText(f"FASTER  /  {self.TITLES[key]}")

    def new_session(self):
        self.navigate("studio")
        self.studio.save_current()
        self.studio.clear()

    def open_session(self, s):
        self.studio.load_session(s)
        self.navigate("studio")

    def toggle_fullscreen(self):
        self.is_full = not self.is_full
        self.showFullScreen() if self.is_full else self.showNormal()

    def exit_fullscreen(self):
        if self.is_full:
            self.toggle_fullscreen()

    # ---- engine / settings reactions ----
    def on_engine_state(self, st):
        self.state = st
        s = self.settings
        text = {"loading": "Loading speech engine…",
                "recording": f"Recording… press {pretty_hk(s.get('hk_stop'))}" + (" or say “stop writing”" if s.get("voice_cmds") else ""),
                "transcribing": "Transcribing…",
                "idle": f"Listening… press {pretty_hk(s.get('hk_start'))}" + (" or say “Hey Faster”" if s.get("voice_cmds") else "")}[st]
        self.topbar.pill.set(text, st)
        self.studio.set_state(st)

    def on_model_state(self, st, name):
        self.sidebar.model_lbl.setText(f"Local whisper · {name}")
        self.sidebar.chip.set({"loading": "LOADING", "ready": "READY", "error": "ERROR"}[st], {"ready": "idle"}.get(st, st))
        if st == "ready":
            self.toast.popup("✓  Speech engine ready")

    def on_store_changed(self):
        self.sidebar.update_recent()
        self.studio.st_saved.set_value(len(self.store.items))

    def on_setting(self, k):
        v = self.settings.get(k)
        if k == "accent":
            T.set_accent(v)
            self.restyle()
        elif k == "glow":
            T.glow = int(v) / 100
            self.restyle()
        elif k == "animated_bg":
            self.backdrop.animated = bool(v)
        elif k == "on_top":
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(v))
            self.show()
            enable_dark_titlebar(self)
        elif k in ("hk_start", "hk_stop"):
            self.apply_hotkeys()
        elif k == "voice_cmds":
            self.on_engine_state(self.state)

    def restyle(self):
        QApplication.instance().setStyleSheet(build_qss())
        for b in self.findChildren(NeonButton):
            b._sync_fx()
        self.studio.refresh()
        self.backdrop.update()

    def cycle_accent(self):
        names = list(ACCENTS)
        self.settings.set("accent", names[(names.index(T.name) + 1) % len(names)])

    def apply_hotkeys(self):
        a, b = self.settings.get("hk_start"), self.settings.get("hk_stop")
        if not self.engine.set_hotkeys(a, b):
            self.toast.popup("Couldn't register hotkeys (try running as administrator)")
        self.sidebar.set_hotkeys(a, b)
        self.studio.set_hotkeys(a)
        self.on_engine_state(self.state)

    def reload_engine(self):
        if self.engine.is_recording:
            self.engine.stop_recording()
        self.engine.start_stream()
        self.engine.load_model()
        self.toast.popup("Reloading speech engine…")

    # ---- export / data ----
    def export_text(self, title, text):
        if not text:
            self.toast.popup("Nothing to export yet")
            return
        name = re.sub(r'[\\/:*?"<>|]+', "_", title).strip() or "transcript"
        path, _ = QFileDialog.getSaveFileName(self, "Export transcript", f"{name}.txt", "Text (*.txt);;Markdown (*.md)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.toast.popup("✓  Exported")
            except Exception as ex:
                self.toast.popup(f"Export failed: {str(ex)[:40]}")

    def export_all(self):
        if not self.store.items:
            self.toast.popup("Nothing to export yet")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export archive", "faster-archive.md", "Markdown (*.md)")
        if path:
            body = "\n\n---\n\n".join(f"## {s['title']}\n*{s.get('date', '')} {s['time']}*\n\n{s['text']}" for s in reversed(self.store.items))
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("# Faster archive\n\n" + body)
                self.toast.popup("✓  Archive exported")
            except Exception as ex:
                self.toast.popup(f"Export failed: {str(ex)[:40]}")

    def clear_archive(self):
        if not self.store.items:
            return
        if QMessageBox.question(self, "Delete all sessions", "Permanently delete every saved session?") == QMessageBox.StandardButton.Yes:
            self.store.clear()
            self.toast.popup("Archive cleared")

    # ---- window events ----
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if getattr(self, "toast", None):
            self.toast.reposition()

    def closeEvent(self, e):
        self.engine.shutdown()
        e.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Faster")
    app.setFont(font(10))
    win = MainWindow()
    win.show()
    enable_dark_titlebar(win)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()