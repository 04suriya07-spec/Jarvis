"""
Javris Gesture — Floating System Overlay
─────────────────────────────────────────
Always-on-top semi-transparent window that shows the active gesture mode,
current gesture, and contextual hints — visible even when Javris web UI
is behind another window (e.g. Chrome, VS Code).

Runs entirely in its own daemon thread using tkinter.
Updates are pushed via a thread-safe queue (never call tk from other threads).
"""

from __future__ import annotations

import queue
import threading
import time
from typing import Optional


# ── Visual constants ──────────────────────────────────────────────

_BG      = "#050810"
_BORDER  = "#162035"

_COLORS = {
    "normal": "#00d4ff",
    "cursor": "#00c8ff",
    "scroll": "#10b981",
}

_MODE_LABELS = {
    "normal": "● NORMAL",
    "cursor": "⊕  CURSOR MODE",
    "scroll": "↕  SCROLL MODE",
}

_MODE_HINTS = {
    "normal":  "point=cursor  rock=scroll  3=voice",
    "cursor":  "pinch=click  peace=right  ↑↓=scroll  3=back  4=fwd  palm=exit",
    "scroll":  "move hand up/down to scroll  •  palm / point / fist = exit",
}


class GestureOverlay:
    """
    Lightweight always-on-top overlay for gesture feedback.

    Usage::

        overlay = GestureOverlay()
        overlay.start()

        overlay.update("cursor", "pinch", "drag")
        overlay.stop()
    """

    def __init__(self, corner: str = "bottom-right"):
        self._corner = corner
        self._q: queue.Queue = queue.Queue(maxsize=32)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._tk_ready = threading.Event()

        # Tkinter widget references (set inside thread)
        self._root = None
        self._lbl_mode = None
        self._lbl_gesture = None
        self._lbl_hint = None
        self._after_id = None

        # State for auto-hide
        self._last_gesture_time: float = 0.0

    # ── Public API ─────────────────────────────────────────────────

    def start(self) -> bool:
        """Start overlay in background thread. Returns False if tkinter unavailable."""
        try:
            import tkinter  # noqa: F401 — just verify availability
        except ImportError:
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="GestureOverlay"
        )
        self._thread.start()
        self._tk_ready.wait(timeout=3.0)  # wait until root is up
        return True

    def update(self, mode: str, gesture: str = "", action: str = "") -> None:
        """Thread-safe update. Call from any thread."""
        try:
            self._q.put_nowait({"mode": mode, "gesture": gesture, "action": action})
        except queue.Full:
            pass

    def stop(self) -> None:
        self._running = False
        if self._root:
            try:
                self._root.after(0, self._root.quit)
            except Exception:
                pass

    # ── Internal (runs in overlay thread) ─────────────────────────

    def _run(self) -> None:
        try:
            import tkinter as tk

            self._root = tk.Tk()
            root = self._root

            root.overrideredirect(True)          # no title bar / frame
            root.attributes("-topmost", True)    # always on top
            root.attributes("-alpha", 0.88)
            root.configure(bg=_BG)

            W, H = 300, 78
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()

            if self._corner == "bottom-right":
                x, y = sw - W - 20, sh - H - 60
            elif self._corner == "bottom-left":
                x, y = 20, sh - H - 60
            elif self._corner == "top-right":
                x, y = sw - W - 20, 60
            else:
                x, y = 20, 60

            root.geometry(f"{W}x{H}+{x}+{y}")

            # ── Widgets ──────────────────────────────────────────
            frame = tk.Frame(root, bg=_BG, bd=1, relief="flat",
                             highlightbackground=_BORDER, highlightthickness=1)
            frame.pack(fill="both", expand=True, padx=1, pady=1)

            self._lbl_mode = tk.Label(
                frame, text=_MODE_LABELS["normal"],
                fg=_COLORS["normal"], bg=_BG,
                font=("Consolas", 10, "bold"),
                anchor="w", padx=8, pady=3,
            )
            self._lbl_mode.pack(fill="x")

            self._lbl_gesture = tk.Label(
                frame, text="—",
                fg="#e2e8f0", bg=_BG,
                font=("Consolas", 9),
                anchor="w", padx=8,
            )
            self._lbl_gesture.pack(fill="x")

            self._lbl_hint = tk.Label(
                frame, text=_MODE_HINTS["normal"],
                fg="#3d5878", bg=_BG,
                font=("Consolas", 7),
                anchor="w", padx=8, pady=2,
                wraplength=W - 16,
            )
            self._lbl_hint.pack(fill="x")

            self._tk_ready.set()
            self._poll()
            root.mainloop()

        except Exception:
            self._tk_ready.set()  # unblock callers even on failure

    def _poll(self) -> None:
        """Drain the update queue and schedule the next poll."""
        if not self._running:
            return
        try:
            while True:
                msg = self._q.get_nowait()
                self._apply(msg)
        except queue.Empty:
            pass
        except Exception:
            pass
        self._after_id = self._root.after(40, self._poll)  # ~25 Hz

    def _apply(self, msg: dict) -> None:
        mode    = msg.get("mode", "normal")
        gesture = msg.get("gesture", "")
        action  = msg.get("action", "")

        color = _COLORS.get(mode, _COLORS["normal"])

        self._lbl_mode.configure(
            text=_MODE_LABELS.get(mode, mode.upper()),
            fg=color,
        )

        if gesture and gesture != "unknown":
            display = gesture.replace("_", " ").upper()
            if action:
                display += f"  →  {action.replace('_', ' ')}"
            self._lbl_gesture.configure(text=display, fg="#e2e8f0")
            self._last_gesture_time = time.time()
        elif time.time() - self._last_gesture_time > 2.5:
            self._lbl_gesture.configure(text="—", fg="#3d5878")

        self._lbl_hint.configure(
            text=_MODE_HINTS.get(mode, ""),
            fg=color if mode != "normal" else "#3d5878",
        )

        # Flash border on gesture
        if gesture and gesture not in ("unknown", ""):
            self._root.configure(highlightbackground=color, highlightthickness=1)
            self._root.after(300, lambda: self._root.configure(
                highlightbackground=_BORDER, highlightthickness=1
            ) if self._root else None)
