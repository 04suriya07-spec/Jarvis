"""
Javris Gesture — Main Orchestrator: GestureController
───────────────────────────────────────────────────────
Ties together all modules into a single runtime:

  CameraFeed  →  LandmarkProcessor  →  GestureDetector
     →  GestureSmoother  →  GestureMapper  →  SystemController
     →  JavrisBridge (async event queue)

Usage (standalone)::

    controller = GestureController()
    controller.start()           # opens camera, background thread
    await controller.run_async() # async event loop

Usage (embedded in Javris)::

    controller = GestureController()
    controller.set_assistant(assistant)
    controller.set_voice_engine(voice_engine)
    await controller.start_embedded()
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from gesture.vision_module.camera_feed import CameraFeed, CameraFrame
from gesture.gesture_engine.landmark_processor import LandmarkProcessor
from gesture.gesture_engine.gesture_detector import GestureDetector
from gesture.gesture_engine.gesture_smoother import GestureSmoother
from gesture.command_mapper.mapper import GestureMapper
from gesture.system_controller.actions import SystemController
from gesture.integration_layer.javris_bridge import JavrisBridge, GestureEvent

logger = logging.getLogger("javris.gesture")

CONFIG_DIR = Path(__file__).parent / "config"


class GestureController:
    """
    Full gesture control pipeline.

    Thread model
    ─────────────
    • CameraFeed runs in its own daemon thread (blocking I/O).
    • _process_loop runs in a second daemon thread (CPU-bound CV work).
    • GestureController exposes an asyncio Queue for integration.
    • The JavrisBridge consumes the asyncio Queue.
    """

    def __init__(
        self,
        camera_id: int = 0,
        show_preview: bool = True,
        config_path: Optional[Path] = None,
    ):
        self.show_preview = show_preview

        # Module instances
        self._feed = CameraFeed(camera_id=camera_id)
        self._processor = LandmarkProcessor()
        self._detector = GestureDetector()
        self._mapper = GestureMapper(config_path or CONFIG_DIR / "gesture_mappings.json")
        self._controller = SystemController()
        self._bridge = JavrisBridge()

        # Load settings from config
        settings = self._mapper.get_settings()
        sequences = self._mapper._sequences  # access internal — same object lifetime

        self._smoother = GestureSmoother(
            window=settings.get("smoothing_frames", 8),
            threshold=settings.get("confirmation_threshold", 0.70),
            cooldown=settings.get("cooldown_seconds", 1.5),
            sequence_timeout=settings.get("sequence_timeout_seconds", 2.5),
            sequences=sequences,
        )

        # Async event queue (GestureEvent objects)
        self.event_queue: asyncio.Queue = asyncio.Queue(maxsize=32)

        # Cursor control mode state
        self._cursor_mode = False

        # Display settings
        self._settings = settings
        self._active_color  = tuple(settings.get("feedback_color_active", [0, 255, 100]))
        self._idle_color    = tuple(settings.get("feedback_color_idle", [100, 100, 100]))

        # Runtime state
        self.running = False
        self._process_thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Stats
        self.stats = {
            "frames_processed": 0,
            "gestures_confirmed": 0,
            "actions_executed": 0,
            "start_time": 0.0,
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
        """Open camera and start processing thread.  Returns False if camera unavailable."""
        if not self._feed.start():
            logger.error("Camera not available — gesture control cannot start")
            return False

        self.running = True
        self.stats["start_time"] = time.time()

        self._process_thread = threading.Thread(
            target=self._process_loop,
            daemon=True,
            name="GestureProcessor",
        )
        self._process_thread.start()
        logger.info("GestureController started")
        return True

    def stop(self) -> None:
        """Stop all processing and release camera."""
        self.running = False
        self._feed.stop()
        self._bridge.stop()
        if self._process_thread:
            self._process_thread.join(timeout=3.0)
        if self.show_preview:
            cv2.destroyWindow("Javris — Gesture Control")
        logger.info("GestureController stopped")

    # ── Async entry points ────────────────────────────────────────

    async def run_async(self) -> None:
        """
        Start the controller and run the bridge consumer loop.
        Blocks until Ctrl+C or stop() is called.
        """
        self._loop = asyncio.get_event_loop()
        ok = self.start()
        if not ok:
            return

        try:
            await self._bridge.consume_queue(self.event_queue)
        finally:
            self.stop()

    async def start_embedded(self) -> None:
        """
        Start in embedded mode (called from Javris server).
        Spawns processing thread and bridge consumer as asyncio task.
        """
        self._loop = asyncio.get_event_loop()
        ok = self.start()
        if ok:
            asyncio.create_task(self._bridge.consume_queue(self.event_queue))
            logger.info("Gesture control embedded into Javris event loop")

    # ── Processing loop (background thread) ───────────────────────

    def _process_loop(self) -> None:
        """Main processing loop — runs in a dedicated thread."""
        while self.running:
            frame = self._feed.get_frame(timeout=0.05)
            if frame is None:
                continue

            self._process_frame(frame)

            if self.show_preview:
                self._show_preview(frame)

    def _process_frame(self, frame: CameraFrame) -> None:
        """Run the full pipeline on one camera frame."""
        self.stats["frames_processed"] += 1

        if not frame.hands:
            self._smoother._history.append("unknown")
            return

        hand = frame.hands[0]   # primary hand only

        # Update wrist history for swipe detection
        wx, wy, _ = hand.wrist
        self._smoother.update_wrist(wx, wy)

        # Process landmarks → HandState
        hand_state = self._processor.process(hand)

        # Detect raw gesture
        raw_result = self._detector.detect(
            hand_state,
            wrist_history=self._smoother.get_wrist_history(),
        )

        # Smooth and apply cooldown
        confirmed = self._smoother.feed(raw_result)
        if confirmed is None:
            return

        self.stats["gestures_confirmed"] += 1
        logger.debug(f"Gesture confirmed: {confirmed.name} ({confirmed.confidence:.2f})")

        # Handle cursor mode separately
        if confirmed.name == "cursor_mode" or self._cursor_mode:
            self._handle_cursor_mode(hand_state, confirmed)
            return

        # Resolve to command intent
        intent = self._mapper.resolve(confirmed)
        if intent is None:
            return

        # Execute system action
        result = self._controller.execute(intent.action, intent.params)
        if result.success:
            self.stats["actions_executed"] += 1
            logger.info(f"Action: {intent.action} → {result.message}")

        # Push event to async queue (thread-safe)
        if self._loop and not self._loop.is_closed():
            event = GestureEvent(intent=intent, gesture=confirmed)
            try:
                self._loop.call_soon_threadsafe(
                    self._put_event_nowait, event
                )
            except RuntimeError:
                pass  # loop may have stopped

        # Handle cursor mode activation
        if intent.action == "cursor_mode":
            self._cursor_mode = True
            logger.info("Entering cursor control mode")

        # Handle voice activation signal
        if intent.action == "activate_voice":
            self._put_event_async(GestureEvent(intent=intent, gesture=confirmed))

    def _put_event_nowait(self, event: GestureEvent) -> None:
        try:
            self.event_queue.put_nowait(event)
        except asyncio.QueueFull:
            pass  # drop on overflow — gestures are real-time events

    def _put_event_async(self, event: GestureEvent) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._put_event_nowait, event)

    # ── Cursor control mode ───────────────────────────────────────

    def _handle_cursor_mode(self, hand_state, confirmed) -> None:
        """
        In cursor mode, the index finger tip controls the mouse cursor.
        Exit cursor mode with a closed fist.
        """
        if confirmed.name == "closed_fist":
            self._cursor_mode = False
            logger.info("Exiting cursor control mode")
            return

        sensitivity = self._settings.get("cursor_mode_sensitivity", 2.5)
        tip_x = hand_state.index_tip_x
        tip_y = hand_state.index_tip_y

        self._controller.execute("move_cursor", {
            "x_norm": tip_x,
            "y_norm": tip_y,
        })

    # ── Visual feedback (preview window) ─────────────────────────

    def _show_preview(self, frame: CameraFrame) -> None:
        """Draw annotations on the frame and display the preview window."""
        annotated = self._feed.get_annotated_frame()
        if annotated is None:
            return

        h, w = annotated.shape[:2]
        current = self._smoother.current_gesture
        color = self._active_color if current != "unknown" else self._idle_color

        # Gesture label
        if self._settings.get("show_gesture_label", True):
            label = f"Gesture: {current.upper().replace('_', ' ')}"
            cv2.putText(
                annotated, label,
                (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                color, 2, cv2.LINE_AA,
            )

        # Cursor mode indicator
        if self._cursor_mode:
            cv2.putText(
                annotated, "CURSOR MODE",
                (10, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (0, 200, 255), 2, cv2.LINE_AA,
            )

        # Cooldown bar for current gesture
        if self._settings.get("show_cooldown_bar", True) and current != "unknown":
            remaining = self._smoother.remaining_cooldown(current)
            if remaining > 0:
                ratio = remaining / self._smoother.cooldown
                bar_w = int(w * 0.4)
                filled = int(bar_w * (1 - ratio))
                cv2.rectangle(annotated, (10, h - 25), (10 + bar_w, h - 10), (50, 50, 50), -1)
                cv2.rectangle(annotated, (10, h - 25), (10 + filled, h - 10), color, -1)
                cv2.putText(
                    annotated, "COOLDOWN",
                    (bar_w + 15, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (180, 180, 180), 1, cv2.LINE_AA,
                )

        # FPS counter
        cv2.putText(
            annotated, f"FPS: {frame.fps:.1f}",
            (w - 110, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
            (200, 200, 200), 1, cv2.LINE_AA,
        )

        # Action counter
        cv2.putText(
            annotated, f"Actions: {self.stats['actions_executed']}",
            (w - 130, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
            (180, 180, 180), 1, cv2.LINE_AA,
        )

        # Hand count
        hand_text = f"Hands: {len(frame.hands)}"
        cv2.putText(
            annotated, hand_text,
            (10, h - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
            (200, 200, 200), 1, cv2.LINE_AA,
        )

        cv2.imshow("Javris — Gesture Control", annotated)

        # Allow OpenCV to process window events; 'q' quits
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            self.running = False
