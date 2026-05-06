"""
Javris Gesture — System Controller: Actions
─────────────────────────────────────────────
Executes OS-level actions triggered by confirmed gestures.

All actions are registered in ACTION_REGISTRY so the mapper can
call any action by name without knowing the implementation.
"""

from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

SYSTEM = platform.system()   # "Windows" | "Darwin" | "Linux"

# ── Action result ─────────────────────────────────────────────────

class ActionResult:
    def __init__(self, success: bool, message: str = "", data: Any = None):
        self.success = success
        self.message = message
        self.data = data

    def __repr__(self):
        status = "OK" if self.success else "FAIL"
        return f"ActionResult({status}: {self.message})"


# ── Individual action implementations ────────────────────────────

def _import_pyautogui():
    import pyautogui
    pyautogui.FAILSAFE = False   # disable corner failsafe during gesture mode
    return pyautogui


def open_application(app: str = "chrome", **_) -> ActionResult:
    """Launch an application by name or executable."""
    try:
        if SYSTEM == "Windows":
            os.startfile(app)
        elif SYSTEM == "Darwin":
            subprocess.Popen(["open", "-a", app])
        else:
            subprocess.Popen([app], start_new_session=True)
        return ActionResult(True, f"Launched {app}")
    except Exception as e:
        return ActionResult(False, str(e))


def pause_media(**_) -> ActionResult:
    """Send media play/pause key."""
    try:
        pag = _import_pyautogui()
        pag.press("playpause")
        return ActionResult(True, "Media play/pause toggled")
    except Exception as e:
        return ActionResult(False, str(e))


def toggle_play_pause(**_) -> ActionResult:
    return pause_media()


def increase_volume(steps: int = 5, **_) -> ActionResult:
    """Raise system volume by `steps` key presses."""
    try:
        pag = _import_pyautogui()
        for _ in range(steps):
            pag.press("volumeup")
        return ActionResult(True, f"Volume +{steps}")
    except Exception as e:
        return ActionResult(False, str(e))


def decrease_volume(steps: int = 5, **_) -> ActionResult:
    """Lower system volume by `steps` key presses."""
    try:
        pag = _import_pyautogui()
        for _ in range(steps):
            pag.press("volumedown")
        return ActionResult(True, f"Volume -{steps}")
    except Exception as e:
        return ActionResult(False, str(e))


def take_screenshot(**_) -> ActionResult:
    """Capture and save a screenshot."""
    try:
        import pyautogui
        from PIL import Image
        from datetime import datetime

        shots_dir = Path("data/screenshots")
        shots_dir.mkdir(parents=True, exist_ok=True)
        name = f"gesture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path = shots_dir / name
        img = pyautogui.screenshot()
        img.save(str(path))
        return ActionResult(True, f"Screenshot saved: {path}", data=str(path))
    except Exception as e:
        return ActionResult(False, str(e))


def switch_window_next(**_) -> ActionResult:
    """Switch to next window (Alt+Tab on Windows/Linux, Cmd+Tab on macOS)."""
    try:
        pag = _import_pyautogui()
        if SYSTEM == "Darwin":
            pag.hotkey("command", "tab")
        else:
            pag.hotkey("alt", "tab")
        return ActionResult(True, "Switched to next window")
    except Exception as e:
        return ActionResult(False, str(e))


def switch_window_prev(**_) -> ActionResult:
    """Switch to previous window (Alt+Shift+Tab)."""
    try:
        pag = _import_pyautogui()
        if SYSTEM == "Darwin":
            pag.hotkey("command", "shift", "tab")
        else:
            pag.hotkey("alt", "shift", "tab")
        return ActionResult(True, "Switched to previous window")
    except Exception as e:
        return ActionResult(False, str(e))


def minimize_window(**_) -> ActionResult:
    """Minimise the active window."""
    try:
        pag = _import_pyautogui()
        if SYSTEM == "Windows":
            pag.hotkey("win", "down")
        elif SYSTEM == "Darwin":
            pag.hotkey("command", "m")
        else:
            pag.hotkey("super", "h")
        return ActionResult(True, "Window minimised")
    except Exception as e:
        return ActionResult(False, str(e))


def scroll_up(clicks: int = 5, **_) -> ActionResult:
    """Scroll up by `clicks`."""
    try:
        pag = _import_pyautogui()
        pag.scroll(clicks)
        return ActionResult(True, f"Scrolled up {clicks}")
    except Exception as e:
        return ActionResult(False, str(e))


def scroll_down(clicks: int = 5, **_) -> ActionResult:
    """Scroll down by `clicks`."""
    try:
        pag = _import_pyautogui()
        pag.scroll(-clicks)
        return ActionResult(True, f"Scrolled down {clicks}")
    except Exception as e:
        return ActionResult(False, str(e))


def press_enter(**_) -> ActionResult:
    """Press Enter key."""
    try:
        pag = _import_pyautogui()
        pag.press("enter")
        return ActionResult(True, "Enter pressed")
    except Exception as e:
        return ActionResult(False, str(e))


def cursor_mode(**_) -> ActionResult:
    """Signal to enter cursor-control mode (handled in GestureController)."""
    return ActionResult(True, "cursor_mode_activated")


def activate_voice(**_) -> ActionResult:
    """Signal to activate voice assistant (handled in integration layer)."""
    return ActionResult(True, "voice_assistant_activated")


def move_cursor(x_norm: float = 0.5, y_norm: float = 0.5, **_) -> ActionResult:
    """Move cursor to normalised screen position."""
    try:
        import pyautogui
        screen_w, screen_h = pyautogui.size()
        px = int(x_norm * screen_w)
        py = int(y_norm * screen_h)
        pyautogui.moveTo(px, py, duration=0.05)
        return ActionResult(True, f"Cursor moved to ({px}, {py})")
    except Exception as e:
        return ActionResult(False, str(e))


# ── Action registry ────────────────────────────────────────────────

ACTION_REGISTRY: Dict[str, Callable] = {
    "open_chrome":         lambda **p: open_application(app=p.get("app", "chrome")),
    "open_application":    open_application,
    "pause_media":         pause_media,
    "toggle_play_pause":   toggle_play_pause,
    "increase_volume":     increase_volume,
    "decrease_volume":     decrease_volume,
    "take_screenshot":     take_screenshot,
    "switch_window_next":  switch_window_next,
    "switch_window_prev":  switch_window_prev,
    "minimize_window":     minimize_window,
    "scroll_up":           scroll_up,
    "scroll_down":         scroll_down,
    "press_enter":         press_enter,
    "cursor_mode":         cursor_mode,
    "activate_voice":      activate_voice,
    "move_cursor":         move_cursor,
}


# ── System Controller class ────────────────────────────────────────

class SystemController:
    """
    Executes OS actions from CommandIntents.

    Supports synchronous and asyncio contexts.
    """

    def execute(self, action: str, params: dict = None) -> ActionResult:
        """Run action synchronously."""
        fn = ACTION_REGISTRY.get(action)
        if not fn:
            return ActionResult(False, f"Unknown action: {action}")
        try:
            return fn(**(params or {}))
        except Exception as e:
            return ActionResult(False, f"{action} raised: {e}")

    async def execute_async(self, action: str, params: dict = None) -> ActionResult:
        """Run action in thread pool (non-blocking from async context)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.execute, action, params)

    def register(self, name: str, fn: Callable) -> None:
        """Register a custom action callable."""
        ACTION_REGISTRY[name] = fn
