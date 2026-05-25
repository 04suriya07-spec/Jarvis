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


def mute_volume(**_) -> ActionResult:
    """Toggle system mute."""
    try:
        pag = _import_pyautogui()
        pag.press("volumemute")
        return ActionResult(True, "Volume muted/unmuted")
    except Exception as e:
        return ActionResult(False, str(e))


def brightness_up(steps: int = 10, **_) -> ActionResult:
    """Increase screen brightness."""
    try:
        if SYSTEM == "Windows":
            subprocess.run(
                ["powershell", "-Command",
                 f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                 f".WmiSetBrightness(1,[Math]::Min(100,"
                 f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness+{steps}))"],
                capture_output=True, timeout=5,
            )
        elif SYSTEM == "Darwin":
            subprocess.run(["osascript", "-e",
                            f"tell application \"System Events\" to key code 144"], timeout=3)
        else:
            subprocess.run(["brightnessctl", "set", f"+{steps}%"], timeout=3)
        return ActionResult(True, f"Brightness +{steps}%")
    except Exception as e:
        return ActionResult(False, str(e))


def brightness_down(steps: int = 10, **_) -> ActionResult:
    """Decrease screen brightness."""
    try:
        if SYSTEM == "Windows":
            subprocess.run(
                ["powershell", "-Command",
                 f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                 f".WmiSetBrightness(1,[Math]::Max(0,"
                 f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness-{steps}))"],
                capture_output=True, timeout=5,
            )
        elif SYSTEM == "Darwin":
            subprocess.run(["osascript", "-e",
                            f"tell application \"System Events\" to key code 145"], timeout=3)
        else:
            subprocess.run(["brightnessctl", "set", f"{steps}%-"], timeout=3)
        return ActionResult(True, f"Brightness -{steps}%")
    except Exception as e:
        return ActionResult(False, str(e))


def lock_screen(**_) -> ActionResult:
    """Lock the screen."""
    try:
        if SYSTEM == "Windows":
            subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"])
        elif SYSTEM == "Darwin":
            subprocess.run(["pmset", "displaysleepnow"])
        else:
            subprocess.run(["loginctl", "lock-session"])
        return ActionResult(True, "Screen locked")
    except Exception as e:
        return ActionResult(False, str(e))


def close_window(**_) -> ActionResult:
    """Close the active window."""
    try:
        pag = _import_pyautogui()
        if SYSTEM == "Darwin":
            pag.hotkey("command", "w")
        else:
            pag.hotkey("alt", "F4")
        return ActionResult(True, "Window closed")
    except Exception as e:
        return ActionResult(False, str(e))


def show_desktop(**_) -> ActionResult:
    """Show/hide the desktop."""
    try:
        pag = _import_pyautogui()
        if SYSTEM == "Windows":
            pag.hotkey("win", "d")
        elif SYSTEM == "Darwin":
            pag.hotkey("command", "f3")
        else:
            pag.hotkey("super", "d")
        return ActionResult(True, "Desktop shown")
    except Exception as e:
        return ActionResult(False, str(e))


def zoom_in(**_) -> ActionResult:
    """Zoom in (Ctrl++)."""
    try:
        pag = _import_pyautogui()
        pag.hotkey("ctrl", "+")
        return ActionResult(True, "Zoomed in")
    except Exception as e:
        return ActionResult(False, str(e))


def zoom_out(**_) -> ActionResult:
    """Zoom out (Ctrl+-)."""
    try:
        pag = _import_pyautogui()
        pag.hotkey("ctrl", "-")
        return ActionResult(True, "Zoomed out")
    except Exception as e:
        return ActionResult(False, str(e))


def browser_back(**_) -> ActionResult:
    """Navigate browser back (Alt+Left)."""
    try:
        pag = _import_pyautogui()
        pag.hotkey("alt", "left")
        return ActionResult(True, "Browser back")
    except Exception as e:
        return ActionResult(False, str(e))


def browser_forward(**_) -> ActionResult:
    """Navigate browser forward (Alt+Right)."""
    try:
        pag = _import_pyautogui()
        pag.hotkey("alt", "right")
        return ActionResult(True, "Browser forward")
    except Exception as e:
        return ActionResult(False, str(e))


def mouse_down(**_) -> ActionResult:
    """Press and hold left mouse button (for drag)."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.mouseDown(button="left")
        return ActionResult(True, "Mouse down")
    except Exception as e:
        return ActionResult(False, str(e))


def mouse_up(**_) -> ActionResult:
    """Release left mouse button (end drag)."""
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.mouseUp(button="left")
        return ActionResult(True, "Mouse up")
    except Exception as e:
        return ActionResult(False, str(e))


def trigger_assistant_chat(**_) -> ActionResult:
    """Open Javris in the default browser and focus the chat panel."""
    try:
        import webbrowser
        webbrowser.open("http://localhost:8000")
        return ActionResult(True, "Opened Javris in browser")
    except Exception as e:
        return ActionResult(False, str(e))


def click_left(x_norm: float = -1.0, y_norm: float = -1.0, **_) -> ActionResult:
    """Left-click at current position or at normalised coords."""
    try:
        import pyautogui
        if x_norm >= 0 and y_norm >= 0:
            screen_w, screen_h = pyautogui.size()
            pyautogui.click(int(x_norm * screen_w), int(y_norm * screen_h))
        else:
            pyautogui.click()
        return ActionResult(True, "Left click")
    except Exception as e:
        return ActionResult(False, str(e))


def click_right(x_norm: float = -1.0, y_norm: float = -1.0, **_) -> ActionResult:
    """Right-click at current position or at normalised coords."""
    try:
        import pyautogui
        if x_norm >= 0 and y_norm >= 0:
            screen_w, screen_h = pyautogui.size()
            pyautogui.rightClick(int(x_norm * screen_w), int(y_norm * screen_h))
        else:
            pyautogui.rightClick()
        return ActionResult(True, "Right click")
    except Exception as e:
        return ActionResult(False, str(e))


def cursor_mode(**_) -> ActionResult:
    """Signal to enter cursor-control mode (handled in GestureController)."""
    return ActionResult(True, "cursor_mode_activated")


def activate_voice(**_) -> ActionResult:
    """Activate the Javris voice assistant via the API."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://localhost:8000/api/voice/listen_once",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3)
        return ActionResult(True, "Voice assistant activated")
    except Exception as e:
        # Fallback: open browser so user can use the mic button
        try:
            import webbrowser
            webbrowser.open("http://localhost:8000")
        except Exception:
            pass
        return ActionResult(True, "Voice triggered (fallback)")


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
    # Application control
    "open_chrome":              lambda **p: open_application(app=p.get("app", "chrome")),
    "open_application":         open_application,
    # Media
    "pause_media":              pause_media,
    "toggle_play_pause":        toggle_play_pause,
    "mute_volume":              mute_volume,
    # Volume
    "increase_volume":          increase_volume,
    "decrease_volume":          decrease_volume,
    # Brightness
    "brightness_up":            brightness_up,
    "brightness_down":          brightness_down,
    # Screenshot
    "take_screenshot":          take_screenshot,
    # Window management
    "switch_window_next":       switch_window_next,
    "switch_window_prev":       switch_window_prev,
    "minimize_window":          minimize_window,
    "close_window":             close_window,
    "show_desktop":             show_desktop,
    # Scroll
    "scroll_up":                scroll_up,
    "scroll_down":              scroll_down,
    # Zoom
    "zoom_in":                  zoom_in,
    "zoom_out":                 zoom_out,
    # Keyboard
    "press_enter":              press_enter,
    # Mouse
    "cursor_mode":              cursor_mode,
    "move_cursor":              move_cursor,
    "click_left":               click_left,
    "click_right":              click_right,
    # System
    "lock_screen":              lock_screen,
    # Browser navigation
    "browser_back":             browser_back,
    "browser_forward":          browser_forward,
    # Mouse drag primitives (used internally by cursor mode)
    "mouse_down":               mouse_down,
    "mouse_up":                 mouse_up,
    # Javris assistant
    "activate_voice":           activate_voice,
    "trigger_assistant_chat":   trigger_assistant_chat,
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
