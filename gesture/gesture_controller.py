"""
Javris Gesture — Main Orchestrator: GestureController
───────────────────────────────────────────────────────
Three operating modes, all handled by one unified pipeline:

  NORMAL mode  — gesture → mapped action (window switch, volume, voice, etc.)
  CURSOR mode  — index-finger tip drives the mouse pointer
  SCROLL mode  — hand Y-position drives page scroll (joystick style)

Mode transitions
────────────────
  NORMAL → CURSOR   pointing gesture confirmed
  NORMAL → SCROLL   rock_on gesture confirmed
  CURSOR → NORMAL   open_palm or closed_fist in cursor gesture table
  SCROLL → NORMAL   open_palm / pointing / closed_fist / peace

Cursor mode details
────────────────────
  • Index tip position → EMA-smoothed mouse movement every frame (bypasses smoother)
  • Raw pinch frames ≥ drag_confirm_frames → mouseDown (drag starts)
  • Pinch released → mouseUp (drag ends)
  • Smoother still feeds for discrete events: right-click, scroll, browser nav, exit
  • Swipe detection disabled in cursor mode (hand movement = cursor movement)

Scroll mode details
────────────────────
  • Wrist Y relative to centre captured at mode entry
  • delta > deadzone → scroll up/down proportionally
  • Throttled to scroll_throttle_seconds to prevent scroll storm
  • Any exit gesture → return to NORMAL

Thread model
─────────────
  CameraFeed thread  →  ProcessLoop thread  →  asyncio event queue
  Overlay thread     (tkinter, daemon, optional)
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Optional

import cv2

from gesture.vision_module.camera_feed import CameraFeed, CameraFrame
from gesture.gesture_engine.landmark_processor import LandmarkProcessor
from gesture.gesture_engine.gesture_detector import GestureDetector
from gesture.gesture_engine.gesture_smoother import GestureSmoother
from gesture.command_mapper.mapper import GestureMapper
from gesture.system_controller.actions import SystemController
from gesture.integration_layer.javris_bridge import JavrisBridge, GestureEvent

logger = logging.getLogger("javris.gesture")

CONFIG_DIR = Path(__file__).parent / "config"


# ── Mode enum ──────────────────────────────────────────────────────

class GestureMode(Enum):
    NORMAL = "normal"
    CURSOR = "cursor"
    SCROLL = "scroll"


# ── Helpers ────────────────────────────────────────────────────────

def _pag():
    """Import pyautogui with failsafe disabled."""
    import pyautogui
    pyautogui.FAILSAFE = False
    return pyautogui


# ── Controller ────────────────────────────────────────────────────

class GestureController:
    """
    Full three-mode gesture pipeline.

    Usage (standalone)::

        ctrl = GestureController()
        await ctrl.run_async()

    Usage (embedded in Javris server)::

        ctrl = GestureController()
        ctrl.set_assistant(assistant)
        await ctrl.start_embedded()
    """

    def __init__(
        self,
        camera_id: int = 0,
        show_preview: bool = True,
        config_path: Optional[Path] = None,
    ):
        self.show_preview = show_preview
        cfg_path = config_path or CONFIG_DIR / "gesture_mappings.json"

        # ── Core modules ───────────────────────────────────────────
        self._feed       = CameraFeed(camera_id=camera_id)
        self._processor  = LandmarkProcessor()
        self._detector   = GestureDetector()
        self._mapper     = GestureMapper(cfg_path)
        self._ctrl       = SystemController()
        self._bridge     = JavrisBridge()

        # ── Load full config ───────────────────────────────────────
        try:
            with open(cfg_path) as f:
                _full = json.load(f)
        except Exception:
            _full = {}

        settings = self._mapper.get_settings()
        self._settings = settings

        self._smoother = GestureSmoother(
            window=settings.get("smoothing_frames", 8),
            threshold=settings.get("confirmation_threshold", 0.70),
            cooldown=settings.get("cooldown_seconds", 1.5),
            sequence_timeout=settings.get("sequence_timeout_seconds", 2.5),
            sequences=self._mapper._sequences,
        )

        # ── Mode-specific gesture override tables ──────────────────
        self._cursor_gestures: dict = _full.get("cursor_mode_gestures", {
            "pinch":       "drag",
            "peace":       "click_right",
            "thumbs_up":   "scroll_up",
            "thumbs_down": "scroll_down",
            "three":       "browser_back",
            "four":        "browser_forward",
            "open_palm":   "exit",
            "closed_fist": "exit",
        })
        self._scroll_gestures: dict = _full.get("scroll_mode_gestures", {
            "pointing":    "exit",
            "open_palm":   "exit",
            "closed_fist": "exit",
            "peace":       "exit",
        })

        # ── Tuning constants ───────────────────────────────────────
        self._alpha          = settings.get("cursor_smoothing_alpha", 0.30)
        self._drag_frames    = settings.get("drag_confirm_frames", 4)
        self._scroll_dz      = settings.get("scroll_mode_deadzone", 0.06)
        self._scroll_max     = settings.get("scroll_mode_max_speed", 8)
        self._scroll_throttle= settings.get("scroll_throttle_seconds", 0.06)

        # ── Mode state ─────────────────────────────────────────────
        self._mode: GestureMode = GestureMode.NORMAL

        # Cursor mode
        self._cx: float = 0.5          # EMA-smoothed cursor X
        self._cy: float = 0.5          # EMA-smoothed cursor Y
        self._raw_pinch: int  = 0      # consecutive raw-pinch frames
        self._drag_active: bool = False # mouseDown is currently held

        # Scroll mode
        self._scroll_center_y: float = 0.5
        self._scroll_last_t:   float = 0.0

        # Two-hand cooldown
        self._two_hand_cooldown: float = 0.0

        # ── Display ────────────────────────────────────────────────
        self._color_active = tuple(settings.get("feedback_color_active", [0, 255, 100]))
        self._color_idle   = tuple(settings.get("feedback_color_idle",   [100, 100, 100]))
        self._color_cursor = tuple(settings.get("cursor_color",          [0, 200, 255]))
        self._color_scroll = tuple(settings.get("scroll_color",          [16, 185, 129]))

        # ── Overlay (optional tkinter HUD) ─────────────────────────
        self._overlay = None
        try:
            from gesture.overlay import GestureOverlay
            self._overlay = GestureOverlay()
            if not self._overlay.start():
                self._overlay = None
                logger.debug("Overlay: tkinter not available, skipping")
        except Exception:
            self._overlay = None

        # ── Runtime ────────────────────────────────────────────────
        self.running = False
        self.event_queue: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._process_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        self.stats = {
            "frames_processed":  0,
            "gestures_confirmed": 0,
            "actions_executed":  0,
            "start_time":        0.0,
        }

    # ── Dependency injection ──────────────────────────────────────

    def set_assistant(self, assistant) -> None:
        self._bridge.set_assistant(assistant)

    def set_voice_engine(self, voice_engine) -> None:
        self._bridge.set_voice_engine(voice_engine)

    def set_autonomy(self, autonomy) -> None:
        self._bridge.set_autonomy(autonomy)

    # ── Lifecycle ─────────────────────────────────────────────────

    def start(self) -> bool:
        if not self._feed.start():
            logger.error("Camera not available — gesture control cannot start")
            return False
        self.running = True
        self.stats["start_time"] = time.time()
        self._process_thread = threading.Thread(
            target=self._process_loop, daemon=True, name="GestureProcessor"
        )
        self._process_thread.start()
        logger.info("GestureController started")
        return True

    def stop(self) -> None:
        # Release any held mouse button before stopping
        if self._drag_active:
            try:
                _pag().mouseUp(button="left")
            except Exception:
                pass
            self._drag_active = False

        self.running = False
        self._feed.stop()
        self._bridge.stop()
        if self._overlay:
            self._overlay.stop()
        if self._process_thread:
            self._process_thread.join(timeout=3.0)
        if self.show_preview:
            cv2.destroyAllWindows()
        logger.info("GestureController stopped")

    # ── Async entry points ────────────────────────────────────────

    async def run_async(self) -> None:
        self._loop = asyncio.get_event_loop()
        if not self.start():
            return
        try:
            await self._bridge.consume_queue(self.event_queue)
        finally:
            self.stop()

    async def start_embedded(self) -> None:
        self._loop = asyncio.get_event_loop()
        if self.start():
            asyncio.create_task(self._bridge.consume_queue(self.event_queue))
            logger.info("Gesture control embedded into Javris event loop")

    # ── Main processing loop ──────────────────────────────────────

    def _process_loop(self) -> None:
        while self.running:
            frame = self._feed.get_frame(timeout=0.05)
            if frame is None:
                continue
            self._process_frame(frame)
            if self.show_preview:
                self._draw_preview(frame)

    def _process_frame(self, frame: CameraFrame) -> None:
        self.stats["frames_processed"] += 1

        if not frame.hands:
            self._smoother._history.append("unknown")
            # Release drag if hand disappears
            if self._drag_active:
                self._end_drag()
            return

        # Two-hand check (only in NORMAL mode to avoid interfering with cursor)
        if self._mode == GestureMode.NORMAL and len(frame.hands) >= 2:
            self._check_two_hand(frame)

        hand = frame.hands[0]
        wx, wy, _ = hand.wrist
        hand_state = self._processor.process(hand)

        # Swipe detection is only relevant in NORMAL mode — in CURSOR/SCROLL
        # the hand is moving for control purposes, not navigation.
        if self._mode == GestureMode.NORMAL:
            self._smoother.update_wrist(wx, wy)
            wrist_hist = self._smoother.get_wrist_history()
        else:
            wrist_hist = None  # disable swipe detection

        raw = self._detector.detect(hand_state, wrist_history=wrist_hist)

        if self._mode == GestureMode.CURSOR:
            self._process_cursor(hand_state, raw)
        elif self._mode == GestureMode.SCROLL:
            self._process_scroll(hand_state, raw)
        else:
            self._process_normal(hand_state, raw)

    # ── NORMAL mode pipeline ──────────────────────────────────────

    def _process_normal(self, hand_state, raw) -> None:
        confirmed = self._smoother.feed(raw)
        if confirmed is None:
            return

        self.stats["gestures_confirmed"] += 1
        logger.debug(f"[normal] confirmed: {confirmed.name}")

        # Mode transitions
        if confirmed.name in ("cursor_mode",) or self._mapper.resolve(confirmed) and \
                self._mapper.resolve(confirmed).action == "cursor_mode":
            self._enter_cursor(hand_state)
            return

        intent = self._mapper.resolve(confirmed)
        if intent is None:
            return

        if intent.action == "scroll_mode":
            self._enter_scroll(hand_state)
            return

        if intent.action == "cursor_mode":
            self._enter_cursor(hand_state)
            return

        result = self._ctrl.execute(intent.action, intent.params)
        if result.success:
            self.stats["actions_executed"] += 1
            logger.info(f"[normal] {intent.action} → {result.message}")

        self._push_event(intent, confirmed)

        if intent.action in ("activate_voice", "trigger_assistant_chat"):
            self._put_event_async(GestureEvent(intent=intent, gesture=confirmed))

        if self._overlay:
            self._overlay.update("normal", confirmed.name, intent.action)

    # ── CURSOR mode pipeline ──────────────────────────────────────

    def _process_cursor(self, hand_state, raw) -> None:
        """
        Per-frame cursor mode handler.

        Every frame:
          1. EMA-smooth the index tip position → move mouse
          2. Track raw pinch frames → mouseDown / mouseUp for drag
          3. Feed smoother for discrete events only
        """
        # 1. Smooth cursor and move mouse (every frame, regardless of gesture)
        self._cx = self._alpha * hand_state.index_tip_x + (1 - self._alpha) * self._cx
        self._cy = self._alpha * hand_state.index_tip_y + (1 - self._alpha) * self._cy
        try:
            pag = _pag()
            sw, sh = pag.size()
            pag.moveTo(int(self._cx * sw), int(self._cy * sh), duration=0)
        except Exception:
            pass

        # 2. Raw pinch → drag (bypass smoother for responsiveness)
        if raw.name == "pinch":
            self._raw_pinch += 1
            if self._raw_pinch == self._drag_frames:
                self._start_drag()
        else:
            if self._drag_active:
                self._end_drag()
            else:
                self._raw_pinch = max(0, self._raw_pinch - 1)

        # 3. Smoother for discrete cursor-mode overrides
        #    Skip pinch (handled above) and unknown
        if raw.name in ("pinch", "unknown"):
            return

        confirmed = self._smoother.feed(raw)
        if confirmed is None:
            return

        action = self._cursor_gestures.get(confirmed.name)
        if action is None:
            return

        logger.debug(f"[cursor] {confirmed.name} → {action}")

        if action == "exit":
            self._exit_to_normal()
            return

        if action == "click_right":
            try:
                _pag().rightClick()
                logger.info("[cursor] right-click")
            except Exception:
                pass
            self.stats["actions_executed"] += 1
            if self._overlay:
                self._overlay.update("cursor", confirmed.name, "right click")
            return

        if action == "scroll_up":
            try:
                _pag().scroll(5)
                logger.info("[cursor] scroll up")
            except Exception:
                pass
            self.stats["actions_executed"] += 1
            if self._overlay:
                self._overlay.update("cursor", confirmed.name, "scroll up")
            return

        if action == "scroll_down":
            try:
                _pag().scroll(-5)
                logger.info("[cursor] scroll down")
            except Exception:
                pass
            self.stats["actions_executed"] += 1
            if self._overlay:
                self._overlay.update("cursor", confirmed.name, "scroll down")
            return

        if action == "browser_back":
            self._ctrl.execute("browser_back", {})
            logger.info("[cursor] browser back")
            self.stats["actions_executed"] += 1
            if self._overlay:
                self._overlay.update("cursor", confirmed.name, "back")
            return

        if action == "browser_forward":
            self._ctrl.execute("browser_forward", {})
            logger.info("[cursor] browser forward")
            self.stats["actions_executed"] += 1
            if self._overlay:
                self._overlay.update("cursor", confirmed.name, "forward")
            return

    def _start_drag(self) -> None:
        if self._drag_active:
            return
        try:
            _pag().mouseDown(button="left")
            self._drag_active = True
            logger.info("[cursor] drag START")
        except Exception:
            pass

    def _end_drag(self) -> None:
        if not self._drag_active:
            return
        try:
            _pag().mouseUp(button="left")
        except Exception:
            pass
        self._drag_active = False
        self._raw_pinch = 0
        logger.info("[cursor] drag END")

    # ── SCROLL mode pipeline ──────────────────────────────────────

    def _process_scroll(self, hand_state, raw) -> None:
        """
        Joystick-style scroll: wrist Y vs centre captured at mode entry.
          • hand above centre → scroll up (speed ∝ distance)
          • hand below centre → scroll down
        """
        # Check exit gestures first
        confirmed = self._smoother.feed(raw)
        if confirmed:
            action = self._scroll_gestures.get(confirmed.name)
            if action == "exit":
                self._exit_to_normal()
                return

        now = time.time()
        if now - self._scroll_last_t < self._scroll_throttle:
            return

        dy = hand_state.wrist_y - self._scroll_center_y

        if abs(dy) <= self._scroll_dz:
            return  # inside dead zone — no scroll

        # Map |dy| → [1, max_speed] scroll clicks
        intensity = abs(dy) - self._scroll_dz
        clicks = max(1, min(self._scroll_max, int(intensity * 40)))

        try:
            if dy < 0:   # hand moved up → scroll page up
                _pag().scroll(clicks)
            else:         # hand moved down → scroll page down
                _pag().scroll(-clicks)
            self._scroll_last_t = now
            self.stats["actions_executed"] += 1
            if self._overlay:
                direction = "↑ scroll up" if dy < 0 else "↓ scroll down"
                self._overlay.update("scroll", "", direction)
        except Exception:
            pass

    # ── Mode transitions ──────────────────────────────────────────

    def _enter_cursor(self, hand_state) -> None:
        # Seed cursor at current index tip so there's no jump
        self._cx = hand_state.index_tip_x
        self._cy = hand_state.index_tip_y
        self._raw_pinch = 0
        self._drag_active = False
        self._mode = GestureMode.CURSOR
        # Reset smoother cooldowns so cursor-mode gestures respond immediately
        self._smoother._last_fire.clear()
        logger.info("→ CURSOR mode")
        if self._overlay:
            self._overlay.update("cursor", "", "")

    def _enter_scroll(self, hand_state) -> None:
        self._scroll_center_y = hand_state.wrist_y
        self._scroll_last_t = 0.0
        self._mode = GestureMode.SCROLL
        self._smoother._last_fire.clear()
        logger.info(f"→ SCROLL mode (centre y={self._scroll_center_y:.2f})")
        if self._overlay:
            self._overlay.update("scroll", "", "")

    def _exit_to_normal(self) -> None:
        if self._drag_active:
            self._end_drag()
        self._mode = GestureMode.NORMAL
        self._smoother._last_fire.clear()
        logger.info("→ NORMAL mode")
        if self._overlay:
            self._overlay.update("normal", "", "")

    # ── Two-hand gestures (NORMAL only) ──────────────────────────

    def _check_two_hand(self, frame: CameraFrame) -> None:
        now = time.time()
        if now - self._two_hand_cooldown < 2.0:
            return

        states   = [self._processor.process(h) for h in frame.hands[:2]]
        patterns = [s.finger_pattern for s in states]

        def _all_ext(p):  return all(p)
        def _all_fold(p): _, i, m, r, p_ = p; return not i and not m and not r and not p_

        action = None
        if _all_ext(patterns[0]) and _all_ext(patterns[1]):
            action = "brightness_up"
        elif _all_fold(patterns[0]) and _all_fold(patterns[1]):
            action = "brightness_down"

        if action:
            result = self._ctrl.execute(action, {})
            if result.success:
                self.stats["actions_executed"] += 1
                self._two_hand_cooldown = now
                logger.info(f"[two-hand] {action}")

    # ── Async event helpers ───────────────────────────────────────

    def _push_event(self, intent, confirmed) -> None:
        if self._loop and not self._loop.is_closed():
            event = GestureEvent(intent=intent, gesture=confirmed)
            try:
                self._loop.call_soon_threadsafe(self._put_event_nowait, event)
            except RuntimeError:
                pass

    def _put_event_nowait(self, event: GestureEvent) -> None:
        try:
            self.event_queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def _put_event_async(self, event: GestureEvent) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._put_event_nowait, event)

    # ── Camera preview window ─────────────────────────────────────

    def _draw_preview(self, frame: CameraFrame) -> None:
        img = self._feed.get_annotated_frame()
        if img is None:
            return

        h, w = img.shape[:2]
        mode  = self._mode
        current = self._smoother.current_gesture

        # ── Mode badge ──────────────────────────────────────────
        if mode == GestureMode.CURSOR:
            badge_color = self._color_cursor
            badge_text  = "CURSOR MODE"
            hint        = "pinch=click/drag  peace=right  thumb=scroll  3=back  4=fwd  palm=exit"
        elif mode == GestureMode.SCROLL:
            badge_color = self._color_scroll
            badge_text  = "SCROLL MODE"
            hint        = "move hand up/down to scroll  |  palm / point / fist = exit"
        else:
            badge_color = self._color_active if current != "unknown" else self._color_idle
            badge_text  = ""
            hint        = ""

        # ── Gesture label ────────────────────────────────────────
        if self._settings.get("show_gesture_label", True):
            label = f"Gesture: {current.upper().replace('_', ' ')}"
            cv2.putText(img, label, (10, 38),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.85, badge_color, 2, cv2.LINE_AA)

        # ── Mode badge row ───────────────────────────────────────
        if badge_text:
            cv2.putText(img, badge_text, (10, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, badge_color, 2, cv2.LINE_AA)
        if hint:
            cv2.putText(img, hint, (10, 92),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, badge_color, 1, cv2.LINE_AA)

        # ── Cursor crosshair ─────────────────────────────────────
        if mode == GestureMode.CURSOR:
            cx = int(self._cx * w)
            cy = int(self._cy * h)
            cv2.drawMarker(img, (cx, cy), self._color_cursor,
                           cv2.MARKER_CROSS, 22, 2, cv2.LINE_AA)
            if self._drag_active:
                cv2.circle(img, (cx, cy), 12, (0, 80, 255), 2, cv2.LINE_AA)
                cv2.putText(img, "DRAG", (cx + 14, cy - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 80, 255), 1, cv2.LINE_AA)

        # ── Scroll level indicator ───────────────────────────────
        if mode == GestureMode.SCROLL:
            # Centre line
            cy_px = int(self._scroll_center_y * h)
            cv2.line(img, (w - 30, cy_px), (w - 10, cy_px), self._color_scroll, 1)
            # Hand position
            # (wrist position tracked externally — show as moving dot)
            cv2.putText(img, "↕", (w - 28, cy_px + 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, self._color_scroll, 1, cv2.LINE_AA)

        # ── Cooldown bar (normal mode only) ─────────────────────
        if mode == GestureMode.NORMAL and self._settings.get("show_cooldown_bar", True) \
                and current != "unknown":
            remaining = self._smoother.remaining_cooldown(current)
            if remaining > 0:
                ratio  = remaining / self._smoother.cooldown
                bar_w  = int(w * 0.4)
                filled = int(bar_w * (1 - ratio))
                cv2.rectangle(img, (10, h - 25), (10 + bar_w, h - 10), (40, 40, 40), -1)
                cv2.rectangle(img, (10, h - 25), (10 + filled, h - 10),
                              self._color_active, -1)
                cv2.putText(img, "COOLDOWN", (bar_w + 15, h - 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1, cv2.LINE_AA)

        # ── Stats overlay ────────────────────────────────────────
        cv2.putText(img, f"FPS:{frame.fps:.0f}",
                    (w - 80, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)
        cv2.putText(img, f"Act:{self.stats['actions_executed']}",
                    (w - 80, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (180, 180, 180), 1)
        cv2.putText(img, f"Hands:{len(frame.hands)}",
                    (10, h - 45), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (180, 180, 180), 1)
        cv2.putText(img, f"Mode:{mode.value.upper()}",
                    (10, h - 62), cv2.FONT_HERSHEY_SIMPLEX, 0.48, badge_color, 1)

        cv2.imshow("Javris — Gesture Control", img)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            self.running = False
        elif key == ord("c"):
            if self._mode != GestureMode.CURSOR:
                logger.info("Keyboard shortcut: entering cursor mode")
                # Fake hand_state is not available here — use centre coords
                self._cx, self._cy = 0.5, 0.5
                self._mode = GestureMode.CURSOR
                if self._overlay:
                    self._overlay.update("cursor", "", "")
        elif key == ord("s"):
            if self._mode != GestureMode.SCROLL:
                self._scroll_center_y = 0.5
                self._mode = GestureMode.SCROLL
                if self._overlay:
                    self._overlay.update("scroll", "", "")
        elif key == ord("n"):
            self._exit_to_normal()

    # ── Public property for server status endpoint ────────────────

    @property
    def mode(self) -> str:
        return self._mode.value

    @property
    def cursor_mode(self) -> bool:
        return self._mode == GestureMode.CURSOR
