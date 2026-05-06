"""
Javris Gesture — Gesture Engine: Gesture Smoother
───────────────────────────────────────────────────
Temporal smoothing, cooldown logic, and gesture sequence detection.

Smoothing
─────────
A gesture is only *confirmed* when it appears in ≥ threshold% of
the last N frames.  This prevents jitter from mis-triggering actions.

Cooldown
────────
Each gesture has a per-name cooldown timer.  After firing, the same
gesture cannot fire again until the cooldown has elapsed.

Sequence Detection
──────────────────
A circular buffer of recently confirmed gestures is checked against
a dictionary of known sequences (e.g. fist→palm = toggle play/pause).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Tuple

from gesture.gesture_engine.gesture_detector import GestureResult


@dataclass
class ConfirmedGesture:
    """A gesture that has passed smoothing and cooldown checks."""
    name: str
    confidence: float
    timestamp: float = field(default_factory=time.time)
    is_sequence: bool = False
    sequence_key: str = ""
    metadata: dict = field(default_factory=dict)


class GestureSmoother:
    """
    Wraps raw GestureResults and emits confirmed ConfirmedGestures.

    Parameters
    ──────────
    window          : number of recent frames to keep
    threshold       : fraction of window frames that must agree (0–1)
    cooldown        : seconds before the same gesture fires again
    """

    def __init__(
        self,
        window: int = 8,
        threshold: float = 0.70,
        cooldown: float = 1.5,
        sequence_timeout: float = 2.5,
        sequences: Optional[Dict[str, dict]] = None,
    ):
        self.window = window
        self.threshold = threshold
        self.cooldown = cooldown
        self.sequence_timeout = sequence_timeout
        self.sequences: Dict[str, dict] = sequences or {}

        # Sliding window of raw gesture names
        self._history: Deque[str] = deque(maxlen=window)

        # Last fire time per gesture name
        self._last_fire: Dict[str, float] = {}

        # Buffer for sequence detection (confirmed gestures)
        self._seq_buffer: Deque[ConfirmedGesture] = deque(maxlen=4)

        # Wrist position history for swipe detection
        self._wrist_history: Deque[Tuple[float, float, float]] = deque(maxlen=10)

        # Current stable gesture (majority in window)
        self.current_gesture: str = "unknown"

    # ── Public API ─────────────────────────────────────────────────

    def update_wrist(self, x: float, y: float) -> None:
        """Push latest wrist position (normalised) for swipe analysis."""
        self._wrist_history.append((x, y, time.time()))

    def get_wrist_history(self) -> List[Tuple[float, float, float]]:
        return list(self._wrist_history)

    def feed(self, raw: GestureResult) -> Optional[ConfirmedGesture]:
        """
        Feed a raw gesture result.

        Returns a ConfirmedGesture if:
          1. The gesture passes the smoothing window check, AND
          2. The per-gesture cooldown has elapsed.

        Also checks for multi-gesture sequences after confirmation.
        """
        self._history.append(raw.name)

        stable = self._dominant(self._history)
        self.current_gesture = stable

        if stable == "unknown":
            return None

        # Smoothing check
        if not self._passes_smoothing(stable):
            return None

        # Cooldown check
        now = time.time()
        if not self._cooldown_elapsed(stable, now):
            return None

        self._last_fire[stable] = now

        confirmed = ConfirmedGesture(
            name=stable,
            confidence=raw.confidence,
            metadata=raw.metadata,
        )

        # Check sequences
        self._seq_buffer.append(confirmed)
        seq_result = self._check_sequences()
        if seq_result:
            return seq_result

        return confirmed

    def reset_cooldown(self, name: str) -> None:
        """Manually clear cooldown for a gesture (testing / override)."""
        self._last_fire.pop(name, None)

    def remaining_cooldown(self, name: str) -> float:
        """Seconds remaining on cooldown for `name`; 0 if not in cooldown."""
        last = self._last_fire.get(name, 0)
        elapsed = time.time() - last
        return max(0.0, self.cooldown - elapsed)

    # ── Internal helpers ───────────────────────────────────────────

    def _passes_smoothing(self, name: str) -> bool:
        if len(self._history) < self.window:
            return False
        count = sum(1 for g in self._history if g == name)
        return count / len(self._history) >= self.threshold

    def _cooldown_elapsed(self, name: str, now: float) -> bool:
        last = self._last_fire.get(name, 0)
        return (now - last) >= self.cooldown

    @staticmethod
    def _dominant(history: Deque[str]) -> str:
        if not history:
            return "unknown"
        counts: Dict[str, int] = {}
        for g in history:
            counts[g] = counts.get(g, 0) + 1
        return max(counts, key=counts.__getitem__)

    def _check_sequences(self) -> Optional[ConfirmedGesture]:
        """
        Check if the latest items in seq_buffer match any known sequence.
        Sequences expire after `sequence_timeout` seconds.
        """
        if not self.sequences or len(self._seq_buffer) < 2:
            return None

        now = time.time()
        # Prune expired entries
        while self._seq_buffer and (now - self._seq_buffer[0].timestamp) > self.sequence_timeout:
            self._seq_buffer.popleft()

        # Build key from last N gesture names in buffer
        for length in range(2, len(self._seq_buffer) + 1):
            recent = list(self._seq_buffer)[-length:]
            key = "+".join(g.name for g in recent)
            if key in self.sequences:
                action_cfg = self.sequences[key]
                seq_confirmed = ConfirmedGesture(
                    name=action_cfg.get("action", key),
                    confidence=0.95,
                    is_sequence=True,
                    sequence_key=key,
                    metadata=action_cfg,
                )
                # Clear the buffer to avoid repeated triggers
                self._seq_buffer.clear()
                return seq_confirmed

        return None
