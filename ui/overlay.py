"""
Javris Iron Man HUD  v3 — Futuristic Per-Mode Layout System
═══════════════════════════════════════════════════════════════
Always-on-top transparent overlay with fully different panel
arrangements per mode (Work / Trading / Dev / Focus / Night / Research).

Each mode has its own window geometry, panel stack, and accent colour.
Mode transitions animate via QPropertyAnimation (opacity + geometry).

Run:  python ui/overlay.py
Deps: pip install PyQt6 websockets psutil httpx
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil

# ── Qt imports ────────────────────────────────────────────────────
from PyQt6.QtCore import (
    Qt, QTimer, QThread, pyqtSignal, QPointF, QRectF, QSize,
    pyqtSlot, QPropertyAnimation, QEasingCurve, QRect, QPoint,
    QSequentialAnimationGroup, QParallelAnimationGroup, QAbstractAnimation,
)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QPainterPath,
    QLinearGradient, QRadialGradient, QKeySequence, QShortcut,
    QFontDatabase, QIcon, QPixmap, QConicalGradient,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFrame, QScrollArea,
    QSystemTrayIcon, QMenu, QSizeGrip, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QStackedWidget, QSplitter,
)

# ── Server config ─────────────────────────────────────────────────
JAVRIS_WS      = "ws://localhost:8000/ws/chat"
JAVRIS_AUTO_WS = "ws://localhost:8000/ws/autonomy"
JAVRIS_API     = "http://localhost:8000"

# ── Mode definitions (mirrors core/modes.py) ─────────────────────
MODE_DEFS = {
    "work":     {"icon": "💼", "name": "WORK",     "accent": "#00d4ff", "bg_alpha": 210},
    "trading":  {"icon": "📈", "name": "TRADING",  "accent": "#10b981", "bg_alpha": 220},
    "dev":      {"icon": "⌨️", "name": "DEV",      "accent": "#7c3aed", "bg_alpha": 200},
    "focus":    {"icon": "🎯", "name": "FOCUS",    "accent": "#f59e0b", "bg_alpha": 180},
    "night":    {"icon": "🌙", "name": "NIGHT",    "accent": "#4f46e5", "bg_alpha": 160},
    "research": {"icon": "🔬", "name": "RESEARCH", "accent": "#ec4899", "bg_alpha": 215},
}


# ═══════════════════════════════════════════════════════════════════
#  Colour palette helper
# ═══════════════════════════════════════════════════════════════════

def qcolor(hex_str: str, alpha: int = 255) -> QColor:
    c = QColor(hex_str)
    c.setAlpha(alpha)
    return c


class Palette:
    """Dynamic palette that updates per mode."""
    def __init__(self, accent_hex: str = "#00d4ff"):
        self.update(accent_hex)

    def update(self, accent_hex: str):
        self.ACCENT    = qcolor(accent_hex)
        self.ACCENT_DIM = qcolor(accent_hex, 80)
        self.ACCENT_GLOW = qcolor(accent_hex, 30)
        self.BG        = QColor(2, 8, 18, 220)
        self.PANEL     = QColor(4, 14, 32, 195)
        self.BORDER    = qcolor(accent_hex, 90)
        self.TEXT      = QColor(195, 235, 255)
        self.DIM       = QColor(80, 140, 170)
        self.WARN      = QColor(255, 165, 0)
        self.DANGER    = QColor(255, 50, 50)
        self.SUCCESS   = QColor(0, 255, 140)
        self.ARC_BG    = QColor(0, 40, 60, 80)
        self.SCAN      = qcolor(accent_hex, 8)


pal = Palette()


# ═══════════════════════════════════════════════════════════════════
#  Utility: glow shadow effect
# ═══════════════════════════════════════════════════════════════════

def make_glow(color: QColor, radius: int = 12) -> QGraphicsDropShadowEffect:
    glow = QGraphicsDropShadowEffect()
    glow.setBlurRadius(radius)
    glow.setColor(color)
    glow.setOffset(0, 0)
    return glow


# ═══════════════════════════════════════════════════════════════════
#  Base HUD Panel
# ═══════════════════════════════════════════════════════════════════

class HUDPanel(QFrame):
    """Glass panel with animated border glow, hex corner accents, scanline overlay."""

    def __init__(self, title: str = "", parent=None):
        super().__init__(parent)
        self._title = title
        self._scan_offset = 0.0
        self._pulse = 0.0
        self._pulse_dir = 1.0

        self._scan_timer = QTimer()
        self._scan_timer.timeout.connect(self._animate)
        self._scan_timer.start(33)   # ~30 fps scanline

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 10, 12, 10)
        self._layout.setSpacing(6)

        if title:
            hdr = QHBoxLayout()
            hdr.setSpacing(6)
            hex_dot = QLabel("⬡")
            hex_dot.setStyleSheet(f"color:{pal.ACCENT.name()};font-size:10px;border:none")
            hdr.addWidget(hex_dot)
            lbl = QLabel(title.upper())
            lbl.setStyleSheet(
                f"color:{pal.ACCENT.name()};font-family:'Consolas','Courier New',monospace;"
                "font-size:10px;font-weight:bold;letter-spacing:1px;border:none"
            )
            hdr.addWidget(lbl)
            hdr.addStretch()
            self._layout.addLayout(hdr)

    def content_layout(self) -> QVBoxLayout:
        return self._layout

    def _animate(self):
        self._scan_offset = (self._scan_offset + 2.0) % self.height()
        self._pulse += 0.04 * self._pulse_dir
        if self._pulse >= 1.0:
            self._pulse_dir = -1.0
        elif self._pulse <= 0.0:
            self._pulse_dir = 1.0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        w, h = rect.width(), rect.height()

        # Background
        p.setBrush(QBrush(pal.PANEL))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 10, 10)

        # Scan line
        if h > 0:
            grad = QLinearGradient(0, self._scan_offset - 40, 0, self._scan_offset + 40)
            grad.setColorAt(0, QColor(0, 0, 0, 0))
            grad.setColorAt(0.5, pal.SCAN)
            grad.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(rect, 10, 10)

        # Pulsing border
        alpha = int(70 + 50 * self._pulse)
        border_color = QColor(pal.ACCENT)
        border_color.setAlpha(alpha)
        p.setPen(QPen(border_color, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 10, 10)

        # Corner hex accents
        accent_pen = QPen(pal.ACCENT, 2)
        p.setPen(accent_pen)
        sz = 12
        for x, y, dx, dy in [
            (rect.left()+1, rect.top()+1,   sz, 0),   (rect.left()+1, rect.top()+1,   0, sz),
            (rect.right()-sz, rect.top()+1, sz, 0),   (rect.right()-1, rect.top()+1,   0, sz),
            (rect.left()+1, rect.bottom()-sz, 0, sz),  (rect.left()+1, rect.bottom()-1, sz, 0),
            (rect.right()-sz, rect.bottom()-1, sz, 0), (rect.right()-1, rect.bottom()-sz, 0, sz),
        ]:
            p.drawLine(QPointF(x, y), QPointF(x + dx, y + dy))

        p.end()


# ═══════════════════════════════════════════════════════════════════
#  Animated HUD Ring (CPU / RAM / Disk / Net)
# ═══════════════════════════════════════════════════════════════════

class HUDRing(QWidget):
    def __init__(self, label: str, color: QColor, size: int = 88, parent=None):
        super().__init__(parent)
        self.label   = label
        self.color   = color
        self._value  = 0.0
        self._anim   = 0.0
        self._text   = "0%"
        self._history: deque[float] = deque(maxlen=60)
        self.setFixedSize(size, size)
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(16)

    def set_value(self, v: float, text: str = ""):
        self._value = max(0.0, min(1.0, v))
        self._text  = text or f"{int(v * 100)}%"
        self._history.append(self._value)

    def _tick(self):
        diff = self._value - self._anim
        if abs(diff) > 0.001:
            self._anim += diff * 0.10
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 9
        thick = 5

        # Outer glow ring
        glow_pen = QPen(QColor(pal.ACCENT.red(), pal.ACCENT.green(), pal.ACCENT.blue(), 20), thick + 8)
        glow_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(glow_pen)
        p.drawArc(QRectF(cx-r, cy-r, r*2, r*2), 225*16, -270*16)

        # Track arc
        pen = QPen(pal.ARC_BG, thick)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(QRectF(cx-r, cy-r, r*2, r*2), 225*16, -270*16)

        # Value arc with colour shift at high load
        color = self.color
        if self._anim > 0.85:
            color = pal.DANGER
        elif self._anim > 0.65:
            color = pal.WARN

        grad_arc = QConicalGradient(cx, cy, 225)
        grad_arc.setColorAt(0,   color)
        grad_arc.setColorAt(0.5, QColor(color.red()//2, color.green()//2, color.blue()//2))
        grad_arc.setColorAt(1,   color)
        arc_pen = QPen(QBrush(grad_arc), thick)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(arc_pen)
        span = int(-270 * 16 * self._anim)
        if span:
            p.drawArc(QRectF(cx-r, cy-r, r*2, r*2), 225*16, span)

        # Glowing tip dot
        if self._anim > 0.01:
            angle_rad = math.radians(225 - 270 * self._anim)
            tx = cx + r * math.cos(angle_rad)
            ty = cy - r * math.sin(angle_rad)
            gd = QRadialGradient(tx, ty, 9)
            gd.setColorAt(0, color)
            gd.setColorAt(0.4, QColor(color.red(), color.green(), color.blue(), 100))
            gd.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(gd))
            p.drawEllipse(QPointF(tx, ty), 6, 6)

        # Centre value
        p.setPen(QPen(pal.TEXT))
        p.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        p.drawText(QRectF(cx-r, cy-12, r*2, 20), Qt.AlignmentFlag.AlignCenter, self._text)

        # Label
        p.setPen(QPen(pal.DIM))
        p.setFont(QFont("Consolas", 7))
        p.drawText(QRectF(cx-r, cy+6, r*2, 14), Qt.AlignmentFlag.AlignCenter, self.label)
        p.end()


# ═══════════════════════════════════════════════════════════════════
#  Sparkline graph widget
# ═══════════════════════════════════════════════════════════════════

class Sparkline(QWidget):
    def __init__(self, label: str = "", color: QColor = None, parent=None):
        super().__init__(parent)
        self.label = label
        self.color = color or pal.ACCENT
        self._data: deque[float] = deque(maxlen=80)
        self.setMinimumHeight(44)

    def push(self, v: float):
        self._data.append(max(0.0, min(1.0, v)))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if len(self._data) < 2:
            p.end()
            return

        pts = list(self._data)
        n   = len(pts)
        dx  = w / max(n - 1, 1)

        # Filled gradient area
        path = QPainterPath()
        path.moveTo(0, h)
        for i, v in enumerate(pts):
            x = i * dx
            y = h - v * (h - 6)
            if i == 0:
                path.lineTo(x, y)
            else:
                path.lineTo(x, y)
        path.lineTo((n - 1) * dx, h)
        path.closeSubpath()

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, QColor(self.color.red(), self.color.green(), self.color.blue(), 80))
        grad.setColorAt(1, QColor(self.color.red(), self.color.green(), self.color.blue(), 5))
        p.fillPath(path, QBrush(grad))

        # Line
        pen = QPen(self.color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        for i in range(1, n):
            x0 = (i - 1) * dx
            y0 = h - pts[i - 1] * (h - 6)
            x1 = i * dx
            y1 = h - pts[i] * (h - 6)
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        # Label
        if self.label:
            p.setPen(QPen(pal.DIM))
            p.setFont(QFont("Consolas", 7))
            p.drawText(2, h - 2, self.label)

        p.end()


# ═══════════════════════════════════════════════════════════════════
#  Toast notification
# ═══════════════════════════════════════════════════════════════════

class Toast(QFrame):
    COLORS = {
        "critical": "#ff3333",
        "high":     "#ff8800",
        "medium":   "#f59e0b",
        "low":      "#00dcff",
        "info":     "#00dcff",
    }

    def __init__(self, message: str, priority: str = "low", parent=None):
        super().__init__(parent)
        self._age = 0
        self._max_age = 120   # 12s at 100ms tick
        color = self.COLORS.get(priority, "#00dcff")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(7)

        dot = QLabel("◉")
        dot.setStyleSheet(f"color:{color};font-size:9px;border:none")
        dot.setFixedWidth(14)
        layout.addWidget(dot)

        lbl = QLabel(message[:100])
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            "color:#c3ebff;font-family:'Consolas','Courier New',monospace;font-size:10px;border:none"
        )
        layout.addWidget(lbl, 1)

        self.setStyleSheet(f"""
            QFrame {{
                background: rgba(4,14,32,215);
                border: 1px solid {color};
                border-left: 3px solid {color};
                border-radius: 6px;
            }}
        """)
        self.setGraphicsEffect(make_glow(qcolor(color, 80), 8))

    def tick(self) -> bool:
        self._age += 1
        return self._age < self._max_age


# ═══════════════════════════════════════════════════════════════════
#  WebSocket worker
# ═══════════════════════════════════════════════════════════════════

class WSWorker(QThread):
    msg_received = pyqtSignal(str)
    connected    = pyqtSignal(bool)

    def __init__(self, url: str):
        super().__init__()
        self.url      = url
        self._running = True
        self._send_q: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self):
        import websockets
        while self._running:
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=10) as ws:
                    self.connected.emit(True)

                    async def sender():
                        while self._running:
                            if self._send_q:
                                await ws.send(self._send_q.pop(0))
                            await asyncio.sleep(0.05)

                    st = asyncio.create_task(sender())
                    try:
                        async for raw in ws:
                            if not self._running:
                                break
                            self.msg_received.emit(raw)
                    finally:
                        st.cancel()
            except Exception:
                pass
            finally:
                self.connected.emit(False)
            if self._running:
                await asyncio.sleep(3)

    def send(self, text: str):
        self._send_q.append(text)

    def stop(self):
        self._running = False
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)


# ═══════════════════════════════════════════════════════════════════
#  Individual panel content widgets
# ═══════════════════════════════════════════════════════════════════

class SystemMetricsPanel(HUDPanel):
    """CPU / RAM / Disk rings + sparklines. Used in all modes."""

    def __init__(self, compact: bool = False, parent=None):
        super().__init__("SYSTEM STATUS", parent)
        self.compact = compact

        ring_row = QHBoxLayout()
        ring_row.setSpacing(4 if compact else 10)

        size = 70 if compact else 85
        self.cpu  = HUDRing("CPU",  pal.ACCENT,   size)
        self.ram  = HUDRing("RAM",  pal.SUCCESS,   size)
        self.disk = HUDRing("DISK", pal.WARN,      size)
        ring_row.addWidget(self.cpu)
        ring_row.addWidget(self.ram)
        ring_row.addWidget(self.disk)
        self.content_layout().addLayout(ring_row)

        if not compact:
            self.cpu_spark  = Sparkline("cpu",  pal.ACCENT)
            self.ram_spark  = Sparkline("ram",  pal.SUCCESS)
            self.content_layout().addWidget(self.cpu_spark)
            self.content_layout().addWidget(self.ram_spark)

        # Clock
        self.clock_lbl = QLabel("00:00:00")
        self.clock_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock_lbl.setStyleSheet(
            f"color:{pal.ACCENT.name()};font-family:'Consolas','Courier New',monospace;"
            "font-size:22px;font-weight:bold;letter-spacing:3px;border:none"
        )
        self.content_layout().addWidget(self.clock_lbl)

        self.date_lbl = QLabel("")
        self.date_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date_lbl.setStyleSheet(
            "color:#4a8090;font-family:'Consolas','Courier New',monospace;font-size:8px;border:none"
        )
        self.content_layout().addWidget(self.date_lbl)

        # Mode badge
        self.mode_lbl = QLabel("💼 WORK MODE")
        self.mode_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_lbl.setStyleSheet(
            f"color:{pal.ACCENT.name()};font-family:'Consolas','Courier New',monospace;"
            "font-size:9px;border:none;margin-top:2px"
        )
        self.content_layout().addWidget(self.mode_lbl)

        self._stats_timer = QTimer()
        self._stats_timer.timeout.connect(self.refresh_stats)
        self._stats_timer.start(2000)

        self._clock_timer = QTimer()
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)

    def refresh_stats(self):
        try:
            cpu  = psutil.cpu_percent() / 100
            ram  = psutil.virtual_memory().percent / 100
            disk_v = psutil.disk_usage("/").percent / 100
        except Exception:
            return
        self.cpu.set_value(cpu)
        self.ram.set_value(ram)
        self.disk.set_value(disk_v)
        if not self.compact:
            self.cpu_spark.push(cpu)
            self.ram_spark.push(ram)

    def _tick_clock(self):
        now = datetime.now()
        self.clock_lbl.setText(now.strftime("%H:%M:%S"))
        self.date_lbl.setText(now.strftime("%A, %d %b %Y").upper())

    def set_mode(self, icon: str, name: str, color: str = "#00dcff"):
        self.mode_lbl.setText(f"{icon} {name}")
        self.mode_lbl.setStyleSheet(
            f"color:{color};font-family:'Consolas','Courier New',monospace;"
            "font-size:9px;border:none;margin-top:2px"
        )


class ChatWidget(HUDPanel):
    message_sent = pyqtSignal(str)

    def __init__(self, title: str = "JAVRIS INTERFACE", parent=None):
        super().__init__(title, parent)
        self._streaming = False
        self._stream_buf = ""

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(160)
        self.log.setStyleSheet("""
            QTextEdit {
                background: rgba(0,6,16,160);
                color: #b4f0ff;
                font-family: 'Consolas','Courier New',monospace;
                font-size: 11px;
                border: none;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        self.content_layout().addWidget(self.log)

        row = QHBoxLayout()
        row.setSpacing(5)
        self.inp = QLineEdit()
        self.inp.setPlaceholderText("Type or say 'Javris…'")
        self.inp.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(0,20,44,180);
                color: #b4f0ff;
                font-family: 'Consolas','Courier New',monospace;
                font-size: 11px;
                border: 1px solid rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},70);
                border-radius: 5px;
                padding: 5px 8px;
            }}
            QLineEdit:focus {{ border-color: {pal.ACCENT.name()}; }}
        """)
        self.inp.returnPressed.connect(self._send)
        row.addWidget(self.inp)

        send_btn = QPushButton("▶")
        send_btn.setFixedSize(32, 32)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},40);
                color: {pal.ACCENT.name()};
                border: 1px solid rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},80);
                border-radius: 5px; font-size:13px;
            }}
            QPushButton:hover {{ background: rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},90); }}
        """)
        send_btn.clicked.connect(self._send)
        row.addWidget(send_btn)
        self.content_layout().addLayout(row)

        self.status_lbl = QLabel("◌ connecting…")
        self.status_lbl.setStyleSheet(
            f"color:{pal.DIM.name()};font-family:'Consolas','Courier New',monospace;font-size:8px;border:none"
        )
        self.content_layout().addWidget(self.status_lbl)

    def _send(self):
        text = self.inp.text().strip()
        if text:
            self.inp.clear()
            self.message_sent.emit(text)
            self._append("you", text)

    def _append(self, role: str, text: str):
        color  = pal.ACCENT.name() if role == "jarvis" else "#507080"
        prefix = "◈ JAVRIS" if role == "jarvis" else "▸ you"
        self.log.append(
            f'<span style="color:{color};font-weight:bold">{prefix}</span>'
            f'<span style="color:#b4f0ff"> {text}</span>'
        )
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def on_ws_message(self, data: dict):
        t = data.get("type", "")
        if t == "start":
            self._streaming = True
            self._stream_buf = ""
            self.status_lbl.setText("◌ thinking…")
        elif t == "chunk":
            chunk = data.get("text", "")
            self._stream_buf += chunk
            if not self._stream_buf.startswith("◈"):
                self.log.append(f'<span style="color:{pal.ACCENT.name()};font-weight:bold">◈ JAVRIS</span> ')
                self._stream_buf = "◈ " + self._stream_buf
            self.log.insertPlainText(chunk)
            self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())
        elif t == "done":
            self._streaming = False
            self._stream_buf = ""
            self.status_lbl.setText("◎ ready")
        elif t == "error":
            self._append("jarvis", "⚠ " + data.get("text", "Error"))
            self.status_lbl.setText("◎ ready")

    def set_online(self, online: bool):
        self.status_lbl.setText("◉ online" if online else "◌ connecting…")
        color = "#00ff78" if online else "#ff4444"
        self.status_lbl.setStyleSheet(
            f"color:{color};font-family:'Consolas','Courier New',monospace;font-size:8px;border:none"
        )


class NewsTicker(HUDPanel):
    """Scrolling news headlines for Trading / Research modes."""

    def __init__(self, parent=None):
        super().__init__("LIVE INTEL FEED", parent)
        self._articles: list[dict] = []

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollBar:vertical { width: 4px; background: rgba(0,0,0,0); }"
            "QScrollBar::handle:vertical { background: rgba(0,200,255,60); border-radius:2px; }"
        )
        self._inner = QWidget()
        self._inner.setStyleSheet("background: transparent;")
        self._list = QVBoxLayout(self._inner)
        self._list.setSpacing(4)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.addStretch()
        self.scroll.setWidget(self._inner)
        self.content_layout().addWidget(self.scroll)

        refresh_btn = QPushButton("↻ Refresh")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},30);
                color: {pal.ACCENT.name()};
                border: 1px solid rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},60);
                border-radius: 4px; font-size: 9px; padding: 3px 8px;
                font-family: 'Consolas','Courier New',monospace;
            }}
            QPushButton:hover {{ background: rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},70); }}
        """)
        refresh_btn.clicked.connect(self._fetch_news)
        self.content_layout().addWidget(refresh_btn)

        self._fetch_news()
        self._auto = QTimer()
        self._auto.timeout.connect(self._fetch_news)
        self._auto.start(300_000)   # refresh every 5 min

    def _fetch_news(self, topic: str = ""):
        def _call():
            try:
                import httpx
                # Use voice command endpoint to fetch news via skill
                params = {"text": f"latest news{' about ' + topic if topic else ''}", "context": "news_panel"}
                r = httpx.post(f"{JAVRIS_API}/api/voice/command", json=params, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    arts = data.get("data", {}).get("articles", [])
                    if arts:
                        self._populate(arts[:8])
            except Exception:
                pass
        threading.Thread(target=_call, daemon=True).start()

    def _populate(self, articles: list[dict]):
        # Clear old items
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for a in articles:
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background: rgba(0,20,38,160);
                    border: 1px solid rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},40);
                    border-radius: 5px;
                    padding: 2px;
                }}
            """)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(7, 5, 7, 5)
            cl.setSpacing(2)

            title_lbl = QLabel(a.get("title", "")[:90])
            title_lbl.setWordWrap(True)
            title_lbl.setStyleSheet(
                "color:#c3ebff;font-family:'Consolas','Courier New',monospace;font-size:10px;border:none"
            )
            cl.addWidget(title_lbl)

            meta = QLabel(f"{a.get('source','')}  ·  {a.get('published','')}")
            meta.setStyleSheet(
                "color:#4a8090;font-family:'Consolas','Courier New',monospace;font-size:8px;border:none"
            )
            cl.addWidget(meta)
            self._list.insertWidget(self._list.count() - 1, card)


class MiniClock(HUDPanel):
    """Night mode — just a giant clock + date."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.clock = QLabel("00:00:00")
        self.clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clock.setStyleSheet(
            f"color:{pal.ACCENT.name()};font-family:'Consolas','Courier New',monospace;"
            "font-size:38px;font-weight:bold;letter-spacing:4px;border:none;margin:20px 0"
        )
        self.content_layout().addWidget(self.clock)

        self.date = QLabel("")
        self.date.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.date.setStyleSheet(
            "color:#4a8090;font-family:'Consolas','Courier New',monospace;font-size:11px;border:none"
        )
        self.content_layout().addWidget(self.date)

        self.mode_dot = QLabel("🌙 NIGHT MODE — System monitoring active")
        self.mode_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_dot.setStyleSheet(
            f"color:{pal.ACCENT.name()};font-family:'Consolas','Courier New',monospace;"
            "font-size:9px;border:none;margin-top:10px;opacity:0.7"
        )
        self.content_layout().addWidget(self.mode_dot)
        self.content_layout().addStretch()

        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(1000)

    def _tick(self):
        now = datetime.now()
        self.clock.setText(now.strftime("%H:%M:%S"))
        self.date.setText(now.strftime("%A, %d %B %Y").upper())


class NotificationFeed(HUDPanel):
    """Live autonomy event feed."""

    def __init__(self, parent=None):
        super().__init__("NOTIFICATIONS", parent)
        self._toasts: list[Toast] = []

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet(
            "QScrollArea { border:none; background:transparent; }"
            "QScrollBar:vertical { width:4px; background:rgba(0,0,0,0); }"
            "QScrollBar::handle:vertical { background:rgba(0,200,255,60); border-radius:2px; }"
        )
        self._inner = QWidget()
        self._inner.setStyleSheet("background:transparent;")
        self._items = QVBoxLayout(self._inner)
        self._items.setSpacing(4)
        self._items.setContentsMargins(0, 0, 0, 0)
        self._items.addStretch()
        self.scroll.setWidget(self._inner)
        self.content_layout().addWidget(self.scroll)

        clear_btn = QPushButton("✕ clear all")
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background: none; color: {pal.DIM.name()};
                border: none; font-size: 8px;
                font-family: 'Consolas','Courier New',monospace;
            }}
            QPushButton:hover {{ color: {pal.DANGER.name()}; }}
        """)
        clear_btn.clicked.connect(self._clear)
        self.content_layout().addWidget(clear_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def add_event(self, message: str, priority: str = "low"):
        if len(self._toasts) >= 20:
            old = self._toasts.pop(0)
            self._items.removeWidget(old)
            old.deleteLater()
        t = Toast(message, priority)
        self._items.insertWidget(self._items.count() - 1, t)
        self._toasts.append(t)
        self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum())

    def _clear(self):
        for t in self._toasts:
            self._items.removeWidget(t)
            t.deleteLater()
        self._toasts.clear()


class ResearchPanel(HUDPanel):
    """Research mode — topic input + summarised results."""

    def __init__(self, parent=None):
        super().__init__("DEEP RESEARCH", parent)

        row = QHBoxLayout()
        self.topic_inp = QLineEdit()
        self.topic_inp.setPlaceholderText("Research topic…")
        self.topic_inp.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(0,20,44,180); color: #b4f0ff;
                font-family: 'Consolas','Courier New',monospace; font-size: 11px;
                border: 1px solid rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},70);
                border-radius: 5px; padding: 5px 8px;
            }}
        """)
        self.topic_inp.returnPressed.connect(self._start_research)
        row.addWidget(self.topic_inp)

        go_btn = QPushButton("⚡")
        go_btn.setFixedSize(32, 32)
        go_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},40);
                color: {pal.ACCENT.name()};
                border: 1px solid rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},80);
                border-radius: 5px; font-size:14px;
            }}
            QPushButton:hover {{ background: rgba({pal.ACCENT.red()},{pal.ACCENT.green()},{pal.ACCENT.blue()},90); }}
        """)
        go_btn.clicked.connect(self._start_research)
        row.addWidget(go_btn)
        self.content_layout().addLayout(row)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("Enter a topic and press ⚡ to start deep research…")
        self.result.setStyleSheet("""
            QTextEdit {
                background: rgba(0,6,16,160); color: #b4f0ff;
                font-family: 'Consolas','Courier New',monospace; font-size: 10px;
                border: none; border-radius: 4px; padding: 6px;
            }
        """)
        self.content_layout().addWidget(self.result)

    def _start_research(self):
        topic = self.topic_inp.text().strip()
        if not topic:
            return
        self.result.setPlainText(f"⚡ Researching: {topic}\n\nConnecting to research agent…")

        def _call():
            try:
                import httpx
                r = httpx.post(f"{JAVRIS_API}/api/research", json={"topic": topic, "depth": 3}, timeout=120)
                if r.status_code == 200:
                    data = r.json()
                    text = data.get("synthesis", data.get("summary", str(data)))
                    self.result.setPlainText(text)
            except Exception as e:
                self.result.setPlainText(f"Research failed: {e}")
        threading.Thread(target=_call, daemon=True).start()


# ═══════════════════════════════════════════════════════════════════
#  Quick mode action bar
# ═══════════════════════════════════════════════════════════════════

class QuickBar(QFrame):
    action_triggered = pyqtSignal(str)

    MODES = [
        ("💼", "work",     "#00d4ff"),
        ("📈", "trading",  "#10b981"),
        ("⌨️",  "dev",     "#7c3aed"),
        ("🎯", "focus",   "#f59e0b"),
        ("🌙", "night",   "#4f46e5"),
        ("🔬", "research","#ec4899"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = "work"
        self._btns: dict[str, QPushButton] = {}
        self._rebuild()

    def _rebuild(self):
        self.setStyleSheet("""
            QFrame {
                background: rgba(2,10,22,180);
                border: 1px solid rgba(0,200,255,50);
                border-radius: 6px;
            }
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(3)

        lbl = QLabel("⬡")
        lbl.setStyleSheet(f"color:{pal.ACCENT.name()};font-size:10px;border:none")
        layout.addWidget(lbl)

        for icon, mode_id, accent in self.MODES:
            btn = QPushButton(icon)
            btn.setFixedSize(26, 26)
            btn.setToolTip(f"{mode_id.capitalize()} Mode")
            active = (mode_id == self._current)
            btn.setStyleSheet(self._btn_style(accent, active))
            btn.clicked.connect(lambda c=False, m=mode_id: self.action_triggered.emit(m))
            layout.addWidget(btn)
            self._btns[mode_id] = btn

        layout.addStretch()

        # Online dot
        self.online_dot = QLabel("●")
        self.online_dot.setStyleSheet("color:#ff4444;font-size:9px;border:none")
        layout.addWidget(self.online_dot)

    def _btn_style(self, accent: str, active: bool) -> str:
        if active:
            return f"""
                QPushButton {{
                    background: rgba({int(accent[1:3],16)},{int(accent[3:5],16)},{int(accent[5:7],16)},90);
                    border: 1px solid {accent};
                    border-radius: 4px; font-size: 12px;
                }}
            """
        return f"""
            QPushButton {{
                background: rgba(0,20,40,140);
                border: 1px solid rgba({int(accent[1:3],16)},{int(accent[3:5],16)},{int(accent[5:7],16)},40);
                border-radius: 4px; font-size: 12px;
            }}
            QPushButton:hover {{
                background: rgba({int(accent[1:3],16)},{int(accent[3:5],16)},{int(accent[5:7],16)},60);
                border-color: {accent};
            }}
        """

    def set_active(self, mode_id: str):
        self._current = mode_id
        for mid, btn in self._btns.items():
            accent = next((a for _, m, a in self.MODES if m == mid), "#00d4ff")
            btn.setStyleSheet(self._btn_style(accent, mid == mode_id))

    def set_online(self, online: bool):
        self.online_dot.setText("●")
        self.online_dot.setStyleSheet(
            f"color:{'#00ff78' if online else '#ff4444'};font-size:9px;border:none"
        )


# ═══════════════════════════════════════════════════════════════════
#  Per-Mode Layout Windows
#
#  Each mode creates a different arrangement of panels in a fresh
#  QWidget. The overlay swaps between them with a cross-fade.
# ═══════════════════════════════════════════════════════════════════

def _style_common() -> str:
    return "background: transparent;"


class WorkLayout(QWidget):
    """
    WORK MODE  —  Chat (large) | System (narrow) | Notifications (bottom)
    ┌───────────────────┬──────────┐
    │                   │  System  │
    │      Chat         │  Status  │
    │                   ├──────────┤
    │                   │ Notifs   │
    └───────────────────┴──────────┘
    """
    def __init__(self, chat: ChatWidget, metrics: SystemMetricsPanel,
                 notifs: NotificationFeed, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_style_common())
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(6)

        main.addWidget(chat, 3)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(metrics, 2)
        right.addWidget(notifs, 1)
        main.addLayout(right, 1)


class TradingLayout(QWidget):
    """
    TRADING MODE  —  News (left) | System compact (right top) | Notifs (right bottom)
    ┌──────────────┬────────────┐
    │              │  Sys Ring  │
    │  News Feed   ├────────────┤
    │              │  Notif     │
    └──────────────┴────────────┘
    """
    def __init__(self, metrics: SystemMetricsPanel, notifs: NotificationFeed,
                 news: NewsTicker, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_style_common())
        main = QHBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(6)

        main.addWidget(news, 2)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(metrics, 1)
        right.addWidget(notifs, 2)
        main.addLayout(right, 1)


class DevLayout(QWidget):
    """
    DEV MODE  —  Chat (top half) | System compact (bottom left) | Notifs (bottom right)
    ┌──────────────────────────────┐
    │           Chat               │
    ├───────────────┬──────────────┤
    │  Sys compact  │   Notifs     │
    └───────────────┴──────────────┘
    """
    def __init__(self, chat: ChatWidget, metrics: SystemMetricsPanel,
                 notifs: NotificationFeed, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_style_common())
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(6)

        main.addWidget(chat, 2)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        bottom.addWidget(metrics, 1)
        bottom.addWidget(notifs, 1)
        main.addLayout(bottom, 1)


class FocusLayout(QWidget):
    """
    FOCUS MODE  —  Full-width chat only, minimal chrome
    ┌──────────────────────────────┐
    │                              │
    │         Chat only            │
    │                              │
    └──────────────────────────────┘
    """
    def __init__(self, chat: ChatWidget, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_style_common())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(chat)


class NightLayout(QWidget):
    """
    NIGHT MODE  —  Giant clock centre | minimal notifs strip below
    ┌──────────────────────────────┐
    │                              │
    │       Giant Clock            │
    │                              │
    ├──────────────────────────────┤
    │  dim notification strip      │
    └──────────────────────────────┘
    """
    def __init__(self, notifs: NotificationFeed, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_style_common())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.clock_widget = MiniClock()
        layout.addWidget(self.clock_widget, 2)
        layout.addWidget(notifs, 1)


class ResearchLayout(QWidget):
    """
    RESEARCH MODE  —  Research (left) | Chat (right) | Notifs slim (bottom)
    ┌──────────────┬──────────────┐
    │   Research   │              │
    │   Panel      │    Chat      │
    │              │              │
    └──────────────┴──────────────┘
    """
    def __init__(self, chat: ChatWidget, notifs: NotificationFeed,
                 research: ResearchPanel, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_style_common())
        main = QVBoxLayout(self)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(research, 1)
        top.addWidget(chat, 1)
        main.addLayout(top, 3)
        main.addWidget(notifs, 1)


# ═══════════════════════════════════════════════════════════════════
#  Mode geometry map — window size per mode
# ═══════════════════════════════════════════════════════════════════

MODE_GEOMETRY = {
    "work":     (440, 640),
    "trading":  (520, 620),
    "dev":      (460, 600),
    "focus":    (380, 480),
    "night":    (360, 420),
    "research": (540, 660),
}


# ═══════════════════════════════════════════════════════════════════
#  Main Overlay Window
# ═══════════════════════════════════════════════════════════════════

class JavrisOverlay(QWidget):
    def __init__(self, screen_index: int = 0):
        super().__init__()
        self._screen_index = screen_index
        self._current_mode = "work"
        self._dragging = False
        self._drag_pos = QPointF()
        self._chat_ws: WSWorker | None = None
        self._auto_ws: WSWorker | None = None

        # Shared panel instances (reused across layouts)
        self._metrics   = SystemMetricsPanel()
        self._notifs    = NotificationFeed()
        self._chat      = ChatWidget()
        self._chat.message_sent.connect(self._send_chat)
        self._news      = NewsTicker()
        self._research  = ResearchPanel()

        # Layouts per mode
        self._layouts: dict[str, QWidget] = {}

        self._setup_window()
        self._build_shell()
        self._build_all_layouts()
        self._apply_mode("work", animate=False)
        self._setup_shortcuts()
        self._setup_tray()
        self._connect_ws()

    # ─── Window ────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowTitle("Javris HUD")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        screens = QApplication.screens()
        if self._screen_index < len(screens):
            scr = screens[self._screen_index].geometry()
        else:
            scr = QApplication.primaryScreen().geometry()
        w, h = MODE_GEOMETRY["work"]
        self.setGeometry(scr.right() - w - 10, scr.top() + 10, w, h)

    # ─── Outer chrome (title bar + quick bar) ──────────────────────

    def _build_shell(self):
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(10, 10, 10, 10)
        self._outer.setSpacing(6)

        # Title bar
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        self._title_lbl = QLabel("⬡  J A V R I S  v3.0")
        self._title_lbl.setStyleSheet(
            f"color:{pal.ACCENT.name()};font-family:'Consolas','Courier New',monospace;"
            "font-size:11px;font-weight:bold;letter-spacing:2px"
        )
        title_row.addWidget(self._title_lbl)
        title_row.addStretch()

        for symbol, slot, color in [("─", self.showMinimized, "#888"), ("✕", QApplication.quit, "#ff4444")]:
            b = QPushButton(symbol)
            b.setFixedSize(22, 22)
            b.setStyleSheet(f"""
                QPushButton {{
                    background:rgba(0,20,40,180);color:{color};
                    border:1px solid rgba(0,200,255,50);border-radius:3px;font-size:10px;
                }}
                QPushButton:hover {{ background:rgba(0,60,90,200); }}
            """)
            b.clicked.connect(slot)
            title_row.addWidget(b)
        self._outer.addLayout(title_row)

        # Quick bar
        self._quick_bar = QuickBar()
        self._quick_bar.action_triggered.connect(self._on_mode_btn)
        self._outer.addWidget(self._quick_bar)

        # Stacked content area
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("background: transparent;")
        self._outer.addWidget(self._stack)

        # Toast strip (floated at bottom)
        self._toast_strip = QVBoxLayout()
        self._toast_strip.setSpacing(3)
        self._outer.addLayout(self._toast_strip)
        self._active_toasts: list[Toast] = []

        t = QTimer(self)
        t.timeout.connect(self._tick_toasts)
        t.start(100)

    def _build_all_layouts(self):
        lay_work     = WorkLayout(self._chat, self._metrics, self._notifs)
        lay_trading  = TradingLayout(self._metrics, self._notifs, self._news)
        lay_dev      = DevLayout(self._chat, self._metrics, self._notifs)
        lay_focus    = FocusLayout(self._chat)
        lay_night    = NightLayout(self._notifs)
        lay_research = ResearchLayout(self._chat, self._notifs, self._research)

        for mode_id, widget in [
            ("work",     lay_work),
            ("trading",  lay_trading),
            ("dev",      lay_dev),
            ("focus",    lay_focus),
            ("night",    lay_night),
            ("research", lay_research),
        ]:
            self._layouts[mode_id] = widget
            self._stack.addWidget(widget)

    # ─── Mode switching ────────────────────────────────────────────

    def _apply_mode(self, mode_id: str, animate: bool = True):
        if mode_id not in self._layouts:
            return

        info = MODE_DEFS.get(mode_id, MODE_DEFS["work"])
        pal.update(info["accent"])

        self._current_mode = mode_id

        # Resize window
        w, h = MODE_GEOMETRY.get(mode_id, (440, 640))
        screen = QApplication.screens()[self._screen_index] \
            if self._screen_index < len(QApplication.screens()) \
            else QApplication.primaryScreen()
        scr = screen.geometry()
        new_x = scr.right() - w - 10
        new_y = scr.top() + 10

        if animate:
            # Crossfade: fade out → swap → fade in
            eff = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(eff)
            fade_out = QPropertyAnimation(eff, b"opacity", self)
            fade_out.setDuration(180)
            fade_out.setStartValue(1.0)
            fade_out.setEndValue(0.0)
            fade_out.setEasingCurve(QEasingCurve.Type.OutCubic)

            fade_in = QPropertyAnimation(eff, b"opacity", self)
            fade_in.setDuration(250)
            fade_in.setStartValue(0.0)
            fade_in.setEndValue(1.0)
            fade_in.setEasingCurve(QEasingCurve.Type.InCubic)

            def _do_swap():
                self._stack.setCurrentWidget(self._layouts[mode_id])
                self.setGeometry(new_x, new_y, w, h)
                self._refresh_styles()
                fade_in.start()

            fade_out.finished.connect(_do_swap)
            fade_out.start()
        else:
            self._stack.setCurrentWidget(self._layouts[mode_id])
            self.setGeometry(new_x, new_y, w, h)
            self._refresh_styles()

        # Update quick bar
        self._quick_bar.set_active(mode_id)

        # Update title
        self._title_lbl.setText(f"⬡  J A V R I S  — {info['name']}")
        self._title_lbl.setStyleSheet(
            f"color:{info['accent']};font-family:'Consolas','Courier New',monospace;"
            "font-size:11px;font-weight:bold;letter-spacing:2px"
        )

        # Update metrics badge
        self._metrics.set_mode(info["icon"], info["name"], info["accent"])

        # Add a toast notification
        self._add_toast(f"{info['icon']} Switched to {info['name'].capitalize()} Mode", "info")

    def _refresh_styles(self):
        """Re-apply accent colour to dynamic style elements."""
        # Minimal refresh — accent colour stored in pal global
        self.update()

    # ─── PyQt slots ────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_mode_btn(self, mode_id: str):
        def _call():
            try:
                import httpx
                httpx.post(f"{JAVRIS_API}/api/modes/switch", json={"mode_id": mode_id}, timeout=5)
            except Exception:
                pass
        threading.Thread(target=_call, daemon=True).start()
        self._apply_mode(mode_id)

    # ─── WebSocket ─────────────────────────────────────────────────

    def _connect_ws(self):
        self._chat_ws = WSWorker(JAVRIS_WS)
        self._chat_ws.msg_received.connect(self._on_chat_msg)
        self._chat_ws.connected.connect(self._quick_bar.set_online)
        self._chat_ws.connected.connect(self._chat.set_online)
        self._chat_ws.start()

        self._auto_ws = WSWorker(JAVRIS_AUTO_WS)
        self._auto_ws.msg_received.connect(self._on_auto_event)
        self._auto_ws.start()

    @pyqtSlot(str)
    def _on_chat_msg(self, raw: str):
        try:
            self._chat.on_ws_message(json.loads(raw))
        except Exception:
            pass

    @pyqtSlot(str)
    def _on_auto_event(self, raw: str):
        try:
            data = json.loads(raw)
            if data.get("type") == "heartbeat":
                return
            msg      = data.get("message", "")
            priority = data.get("priority", "low")
            evt_type = data.get("event_type", "")

            if evt_type == "mode_change":
                extra   = data.get("data", {})
                mode_id = extra.get("mode_id", self._current_mode)
                self._apply_mode(mode_id)
                return

            if msg:
                self._notifs.add_event(msg, priority)
                self._add_toast(msg, priority)
        except Exception:
            pass

    @pyqtSlot(str)
    def _send_chat(self, text: str):
        if self._chat_ws:
            self._chat_ws.send(json.dumps({"message": text}))

    # ─── Toast strip ───────────────────────────────────────────────

    def _add_toast(self, message: str, priority: str = "low"):
        if len(self._active_toasts) >= 3:
            old = self._active_toasts.pop(0)
            self._toast_strip.removeWidget(old)
            old.deleteLater()
        t = Toast(message, priority)
        self._toast_strip.addWidget(t)
        self._active_toasts.append(t)

    def _tick_toasts(self):
        dead = [t for t in self._active_toasts if not t.tick()]
        for t in dead:
            self._toast_strip.removeWidget(t)
            t.deleteLater()
            self._active_toasts.remove(t)

    # ─── Shortcuts ─────────────────────────────────────────────────

    def _setup_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Shift+J"), self).activated.connect(self._toggle_visibility)
        for i, mode in enumerate(["work", "trading", "dev", "focus", "night", "research"], 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self).activated.connect(
                lambda m=mode: self._on_mode_btn(m)
            )

    # ─── System tray ───────────────────────────────────────────────

    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        pm = QPixmap(16, 16)
        pm.fill(pal.ACCENT)
        self._tray.setIcon(QIcon(pm))
        self._tray.setToolTip("Javris HUD v3")

        menu = QMenu()
        menu.addAction("Show / Hide   Ctrl+Shift+J", self._toggle_visibility)
        menu.addSeparator()
        for icon, mode_id, _ in QuickBar.MODES:
            menu.addAction(f"{icon} {mode_id.capitalize()} Mode",
                           lambda m=mode_id: self._on_mode_btn(m))
        menu.addSeparator()
        menu.addAction("Quit", QApplication.quit)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(
            lambda r: self._toggle_visibility()
            if r == QSystemTrayIcon.ActivationReason.Trigger else None
        )
        self._tray.show()

    # ─── Background paint ──────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)

        # Main background
        p.setBrush(QBrush(pal.BG))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 12, 12)

        # Subtle inner glow
        radius = max(rect.width(), rect.height()) / 2
        grad = QRadialGradient(rect.center(), radius)
        grad.setColorAt(0, pal.ACCENT_GLOW)
        grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(rect, 12, 12)

        # Outer border (pulsing handled per-panel; outer is static)
        p.setPen(QPen(pal.BORDER, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 12, 12)

        # Iron Man corner brackets
        p.setPen(QPen(pal.ACCENT, 2))
        sz = 16
        r = rect
        for (x, y, dx, dy) in [
            (r.left()+1, r.top()+1,  sz, 0),  (r.left()+1, r.top()+1,  0, sz),
            (r.right()-sz, r.top()+1,  sz, 0), (r.right()-1, r.top()+1,  0, sz),
            (r.left()+1, r.bottom()-sz, 0, sz), (r.left()+1, r.bottom()-1, sz, 0),
            (r.right()-sz, r.bottom()-1, sz, 0),(r.right()-1, r.bottom()-sz, 0, sz),
        ]:
            p.drawLine(QPointF(x, y), QPointF(x+dx, y+dy))

        p.end()

    # ─── Drag ──────────────────────────────────────────────────────

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._drag_pos = e.globalPosition() - QPointF(self.pos())

    def mouseMoveEvent(self, e):
        if self._dragging and e.buttons() & Qt.MouseButton.LeftButton:
            self.move((e.globalPosition() - self._drag_pos).toPoint())

    def mouseReleaseEvent(self, e):
        self._dragging = False

    # ─── Visibility ────────────────────────────────────────────────

    def _toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event):
        for ws in [self._chat_ws, self._auto_ws]:
            if ws:
                ws.stop()
        if hasattr(self, "_tray"):
            self._tray.hide()
        event.accept()


# ═══════════════════════════════════════════════════════════════════
#  Secondary Monitor Mini-HUD
#  Shows only system rings + clock — no chat, no input
# ═══════════════════════════════════════════════════════════════════

class MiniHUD(QWidget):
    """Read-only status HUD for secondary monitors."""

    def __init__(self, screen_index: int):
        super().__init__()
        self._screen_index = screen_index
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        scr = QApplication.screens()[screen_index].geometry()
        self.setGeometry(scr.right() - 260, scr.top() + 10, 250, 280)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        lbl = QLabel("⬡  J A V R I S")
        lbl.setStyleSheet(
            "color:#00dcff;font-family:'Consolas','Courier New',monospace;"
            "font-size:10px;font-weight:bold;letter-spacing:2px"
        )
        outer.addWidget(lbl)

        panel = SystemMetricsPanel(compact=True)
        outer.addWidget(panel)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QBrush(QColor(2, 8, 18, 200)))
        p.setPen(QPen(QColor(0, 200, 255, 70), 1))
        p.drawRoundedRect(rect, 10, 10)
        p.end()


# ═══════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════

def main():
    if sys.platform == "win32":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass
    else:
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    app = QApplication(sys.argv)
    app.setApplicationName("Javris")
    app.setQuitOnLastWindowClosed(False)

    # Primary HUD
    overlay = JavrisOverlay(screen_index=0)
    overlay.show()

    # Secondary monitor mini-HUDs
    mini_huds: list[MiniHUD] = []
    screens = QApplication.screens()
    for i in range(1, len(screens)):
        mh = MiniHUD(screen_index=i)
        mh.show()
        mini_huds.append(mh)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
