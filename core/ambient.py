"""
Javris Ambient Context — Passive Environmental Awareness
─────────────────────────────────────────────────────────
Runs as a lightweight background thread (not asyncio) to avoid
blocking the event loop with blocking OS calls.

Tracks:
  • Active window title + process name
  • System idle time (seconds since last input)
  • Foreground app category (coding / browser / communication / etc.)
  • Clipboard change detection (SHA256 hash comparison)
  • CPU / RAM snapshot (lightweight, 3s interval)

The snapshot is thread-safe and can be read by the autonomy engine
or injected into the system prompt as ambient context.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from core.logger import get_logger

logger = get_logger("javris.ambient")

_SYSTEM = platform.system()   # "Windows" | "Darwin" | "Linux"


# ── App category classifier ───────────────────────────────────────

_APP_CATEGORIES: dict[str, str] = {
    # Coding / IDE
    "code": "coding", "devenv": "coding", "pycharm": "coding",
    "intellij": "coding", "webstorm": "coding", "vim": "coding",
    "nvim": "coding", "sublime": "coding", "notepad++": "coding",
    # Browsers
    "chrome": "browsing", "firefox": "browsing", "edge": "browsing",
    "brave": "browsing", "safari": "browsing", "opera": "browsing",
    # Communication
    "slack": "communication", "teams": "communication",
    "discord": "communication", "zoom": "communication",
    "telegram": "communication", "whatsapp": "communication",
    "outlook": "communication", "thunderbird": "communication",
    # Terminals
    "cmd": "terminal", "powershell": "terminal", "wt": "terminal",
    "bash": "terminal", "terminal": "terminal", "iterm": "terminal",
    # Documents
    "word": "documents", "excel": "documents", "powerpoint": "documents",
    "acrobat": "documents", "notion": "documents",
    # Media
    "vlc": "media", "spotify": "media", "netflix": "media",
    "youtube": "media", "mpv": "media",
}


def _classify_app(exe_name: str) -> str:
    exe = exe_name.lower().replace(".exe", "")
    for keyword, category in _APP_CATEGORIES.items():
        if keyword in exe:
            return category
    return "general"


# ── OS-specific helpers ───────────────────────────────────────────

def _get_active_window_windows() -> tuple[str, str]:
    """Returns (window_title, exe_name) on Windows using pywin32."""
    try:
        import win32gui
        import win32process
        import win32api
        import psutil

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return "", ""

        title = win32gui.GetWindowText(hwnd)
        
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid <= 0:
            return title, ""

        try:
            proc = psutil.Process(pid)
            exe = proc.name()
        except Exception:
            exe = ""

        return title, exe
    except Exception as e:
        # Fallback to empty if anything fails
        return "", ""


def _get_active_window_macos() -> tuple[str, str]:
    try:
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first application process '
             'whose frontmost is true'],
            capture_output=True, text=True, timeout=2
        )
        app = result.stdout.strip()
        return app, app
    except Exception:
        return "", ""


def _get_active_window_linux() -> tuple[str, str]:
    try:
        result = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True, text=True, timeout=2
        )
        title = result.stdout.strip()
        return title, ""
    except Exception:
        return "", ""


def _get_active_window() -> tuple[str, str]:
    if _SYSTEM == "Windows":
        return _get_active_window_windows()
    elif _SYSTEM == "Darwin":
        return _get_active_window_macos()
    else:
        return _get_active_window_linux()


def _get_idle_time_seconds() -> float:
    """Seconds since last user input. Returns 0 on error."""
    try:
        if _SYSTEM == "Windows":
            import ctypes
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(lii)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return millis / 1000.0
        elif _SYSTEM == "Darwin":
            result = subprocess.run(
                ["ioreg", "-c", "IOHIDSystem"],
                capture_output=True, text=True, timeout=2
            )
            for line in result.stdout.splitlines():
                if "HIDIdleTime" in line:
                    ns = int(line.split("=")[-1].strip())
                    return ns / 1e9
    except Exception:
        pass
    return 0.0


def _get_clipboard_hash() -> str:
    """Returns a change-detection token for the clipboard without reading its content.

    Uses GetClipboardSequenceNumber — a single atomic Win32 call that is safe
    to call from any thread (no OpenClipboard / message-queue required).
    """
    try:
        if _SYSTEM == "Windows":
            import ctypes
            seq = ctypes.windll.user32.GetClipboardSequenceNumber()
            return str(seq)
    except Exception:
        pass
    return ""


# ── Snapshot dataclass ────────────────────────────────────────────

@dataclass
class AmbientSnapshot:
    window_title: str = ""
    exe_name: str = ""
    app_category: str = "general"
    idle_seconds: float = 0.0
    clipboard_hash: str = ""
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_context_string(self) -> str:
        """One-line summary suitable for injection into system prompt."""
        parts = []
        if self.app_category != "general":
            parts.append(f"currently {self.app_category}")
        if self.window_title:
            parts.append(f"window: \"{self.window_title[:60]}\"")
        idle_min = int(self.idle_seconds // 60)
        if idle_min > 5:
            parts.append(f"idle {idle_min}min")
        if self.cpu_percent > 70:
            parts.append(f"CPU {self.cpu_percent:.0f}%")
        return ", ".join(parts) if parts else "active"

    def to_dict(self) -> dict:
        return {
            "window_title": self.window_title,
            "exe_name": self.exe_name,
            "app_category": self.app_category,
            "idle_seconds": round(self.idle_seconds, 1),
            "cpu_percent": self.cpu_percent,
            "mem_percent": self.mem_percent,
            "timestamp": self.timestamp,
        }


# ── Ambient Watcher ───────────────────────────────────────────────

class AmbientWatcher:
    """
    Lightweight background thread that refreshes an AmbientSnapshot
    every `interval` seconds.

    Thread-safe: snapshot property uses a lock.
    """

    def __init__(self, interval: float = 5.0):
        self._interval = interval
        self._snapshot = AmbientSnapshot()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._prev_window = ""
        self._prev_clipboard_hash = ""
        self.on_window_change: Optional[callable] = None   # hook for autonomy

    # ── Public ────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="javris-ambient"
        )
        self._thread.start()
        logger.info("Ambient watcher started")

    def stop(self) -> None:
        self._running = False

    @property
    def snapshot(self) -> AmbientSnapshot:
        with self._lock:
            return self._snapshot

    def context_string(self) -> str:
        return self.snapshot.to_context_string()

    # ── Background loop ───────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                self._refresh()
            except Exception as e:
                logger.debug(f"Ambient refresh error: {e}")
            time.sleep(self._interval)

    def _refresh(self) -> None:
        import psutil
        
        try:
            title, exe = _get_active_window()
        except Exception:
            title, exe = "", ""

        category = _classify_app(exe or title)
        
        try:
            idle = _get_idle_time_seconds()
        except Exception:
            idle = 0.0

        try:
            clip_hash = _get_clipboard_hash()
        except Exception:
            clip_hash = ""

        try:
            cpu = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory().percent
        except Exception:
            cpu, mem = 0.0, 0.0

        snap = AmbientSnapshot(
            window_title=title,
            exe_name=exe,
            app_category=category,
            idle_seconds=idle,
            clipboard_hash=clip_hash,
            cpu_percent=cpu,
            mem_percent=mem,
            timestamp=time.time(),
        )

        with self._lock:
            self._snapshot = snap

        # Fire window-change hook
        if title != self._prev_window and title:
            self._prev_window = title
            if self.on_window_change:
                try:
                    self.on_window_change(title, exe, category)
                except Exception:
                    pass

        # Log clipboard change (no content — privacy)
        if clip_hash and clip_hash != self._prev_clipboard_hash:
            self._prev_clipboard_hash = clip_hash
            logger.debug("Clipboard changed")


# ── Singleton ─────────────────────────────────────────────────────

_watcher: Optional[AmbientWatcher] = None


def get_ambient_watcher() -> AmbientWatcher:
    global _watcher
    if _watcher is None:
        _watcher = AmbientWatcher(interval=5.0)
    return _watcher
