"""
Javris Gesture — Gesture Engine: Gesture Detector
───────────────────────────────────────────────────
Rule-based classifier that maps a HandState to a named gesture.

Supported gestures
──────────────────
  open_palm    — all 5 fingers extended
  closed_fist  — all 5 fingers folded
  pointing     — only index extended
  thumbs_up    — only thumb extended + palm upright
  thumbs_down  — only thumb extended + palm downward
  peace        — index + middle extended (V sign)
  ok           — thumb + index form a circle; other fingers extended
  three        — index + middle + ring extended
  four         — all except thumb extended
  swipe_left / swipe_right / swipe_up / swipe_down
               — detected by wrist velocity (see GestureDetector)
  unknown      — nothing matched

Design for extensibility: each gesture is a small method that
returns True/False.  An ML model can replace this file later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import time

from gesture.gesture_engine.landmark_processor import HandState, distance, THUMB_TIP, INDEX_TIP


GESTURE_NAMES = [
    "open_palm",
    "closed_fist",
    "pointing",
    "thumbs_up",
    "thumbs_down",
    "peace",
    "ok",
    "three",
    "four",
    "swipe_left",
    "swipe_right",
    "swipe_up",
    "swipe_down",
    "unknown",
]


@dataclass
class GestureResult:
    name: str
    confidence: float
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    @property
    def is_unknown(self) -> bool:
        return self.name == "unknown"


class GestureDetector:
    """
    Classifies a HandState into a named gesture.

    Swipe detection uses a position history (supplied externally by
    the smoother) to compute wrist velocity.
    """

    # Fine-tune thresholds here without touching gesture logic
    _PINCH_DIST     = 0.06   # thumb–index distance for "ok" sign
    _SWIPE_MIN_VEL  = 0.012  # normalised units / frame for swipe detection
    _SWIPE_FRAMES   = 6      # number of frames to check for swipe

    def detect(
        self,
        state: HandState,
        wrist_history: Optional[List[Tuple[float, float, float]]] = None,
    ) -> GestureResult:
        """
        Args:
            state:         processed hand state
            wrist_history: last N (x, y, timestamp) tuples for swipe detection
        """
        pattern = state.finger_pattern  # (thumb, index, middle, ring, pinky)

        # -- Dynamic gestures first: swipe overrides static when hand is moving fast --
        if wrist_history and len(wrist_history) >= self._SWIPE_FRAMES:
            swipe = self._detect_swipe(wrist_history)
            if swipe:
                return GestureResult(swipe, 0.85, metadata={"history_len": len(wrist_history)})

        # -- Static gestures (order matters: specific before general) --
        if self._is_ok(state):
            return GestureResult("ok", 0.90)

        if self._is_thumbs_up(state, pattern):
            return GestureResult("thumbs_up", 0.92)

        if self._is_thumbs_down(state, pattern):
            return GestureResult("thumbs_down", 0.90)

        if self._is_pointing(pattern):
            return GestureResult("pointing", 0.93)

        if self._is_peace(pattern):
            return GestureResult("peace", 0.91)

        if self._is_three(pattern):
            return GestureResult("three", 0.88)

        if self._is_four(pattern):
            return GestureResult("four", 0.88)

        if self._is_open_palm(pattern):
            return GestureResult("open_palm", 0.95)

        if self._is_closed_fist(pattern):
            return GestureResult("closed_fist", 0.95)

        return GestureResult("unknown", 0.0)

    # ── Static gesture rules ──────────────────────────────────────

    @staticmethod
    def _is_open_palm(pattern: tuple) -> bool:
        return all(pattern)

    @staticmethod
    def _is_closed_fist(pattern: tuple) -> bool:
        # All fingers folded (thumb may be slightly out — allow some slack)
        _, i, m, r, p = pattern
        return not i and not m and not r and not p

    @staticmethod
    def _is_pointing(pattern: tuple) -> bool:
        t, i, m, r, p = pattern
        return i and not m and not r and not p

    @staticmethod
    def _is_peace(pattern: tuple) -> bool:
        t, i, m, r, p = pattern
        return i and m and not r and not p

    @staticmethod
    def _is_three(pattern: tuple) -> bool:
        t, i, m, r, p = pattern
        return i and m and r and not p

    @staticmethod
    def _is_four(pattern: tuple) -> bool:
        t, i, m, r, p = pattern
        return not t and i and m and r and p

    @staticmethod
    def _is_thumbs_up(state: HandState, pattern: tuple) -> bool:
        t, i, m, r, p = pattern
        if not t or i or m or r or p:
            return False
        # Thumb tip should be above wrist (smaller y)
        return state.raw.landmarks[4][1] < state.raw.landmarks[0][1] - 0.05

    @staticmethod
    def _is_thumbs_down(state: HandState, pattern: tuple) -> bool:
        t, i, m, r, p = pattern
        if not t or i or m or r or p:
            return False
        # Thumb tip below wrist (larger y)
        return state.raw.landmarks[4][1] > state.raw.landmarks[0][1] + 0.05

    @staticmethod
    def _is_ok(state: HandState) -> bool:
        lm = state.raw.landmarks
        dist = distance(lm, THUMB_TIP, INDEX_TIP)
        # Other fingers (middle, ring, pinky) should be extended
        _, _, m, r, p = state.finger_pattern
        return dist < GestureDetector._PINCH_DIST and m and r and p

    # ── Swipe detection ───────────────────────────────────────────

    def _detect_swipe(
        self,
        wrist_history: List[Tuple[float, float, float]],
    ) -> Optional[str]:
        """
        Detect directional swipe from recent wrist positions.
        Each entry is (x, y, timestamp) in normalised coords.
        """
        recent = wrist_history[-self._SWIPE_FRAMES:]
        x0, y0, _ = recent[0]
        x1, y1, _ = recent[-1]
        dx = x1 - x0
        dy = y1 - y0

        abs_dx = abs(dx)
        abs_dy = abs(dy)
        threshold = self._SWIPE_MIN_VEL * self._SWIPE_FRAMES

        if max(abs_dx, abs_dy) < threshold:
            return None

        if abs_dx > abs_dy:
            return "swipe_right" if dx > 0 else "swipe_left"
        else:
            return "swipe_down" if dy > 0 else "swipe_up"
