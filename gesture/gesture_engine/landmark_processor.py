"""
Javris Gesture — Gesture Engine: Landmark Processor
─────────────────────────────────────────────────────
Converts raw MediaPipe landmarks into a structured HandState
with per-finger extension flags and positional metadata.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Tuple

from gesture.vision_module.camera_feed import HandLandmarks


# MediaPipe landmark indices
WRIST          = 0
THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP = 1, 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP = 5, 6, 7, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP = 9, 10, 11, 12
RING_MCP, RING_PIP, RING_DIP, RING_TIP = 13, 14, 15, 16
PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP = 17, 18, 19, 20


@dataclass
class FingerState:
    extended: bool
    curl_ratio: float   # 0.0=fully curled, 1.0=fully extended


@dataclass
class HandState:
    """Structured hand state derived from 21 landmarks."""
    raw: HandLandmarks

    # Per-finger extension
    thumb: FingerState = field(default_factory=lambda: FingerState(False, 0.0))
    index: FingerState = field(default_factory=lambda: FingerState(False, 0.0))
    middle: FingerState = field(default_factory=lambda: FingerState(False, 0.0))
    ring: FingerState = field(default_factory=lambda: FingerState(False, 0.0))
    pinky: FingerState = field(default_factory=lambda: FingerState(False, 0.0))

    # Convenience
    @property
    def extended_count(self) -> int:
        return sum(1 for f in self.fingers if f.extended)

    @property
    def fingers(self) -> List[FingerState]:
        return [self.thumb, self.index, self.middle, self.ring, self.pinky]

    @property
    def finger_pattern(self) -> Tuple[bool, bool, bool, bool, bool]:
        """(thumb, index, middle, ring, pinky) extension flags."""
        return tuple(f.extended for f in self.fingers)  # type: ignore

    # Wrist normalised position [0,1]
    @property
    def wrist_x(self) -> float:
        return self.raw.landmarks[WRIST][0]

    @property
    def wrist_y(self) -> float:
        return self.raw.landmarks[WRIST][1]

    @property
    def index_tip_x(self) -> float:
        return self.raw.landmarks[INDEX_TIP][0]

    @property
    def index_tip_y(self) -> float:
        return self.raw.landmarks[INDEX_TIP][1]

    # Palm orientation — up vector from wrist to middle MCP
    @property
    def palm_up(self) -> bool:
        """True when palm is roughly facing up (wrist below middle MCP)."""
        return self.raw.landmarks[WRIST][1] > self.raw.landmarks[MIDDLE_MCP][1]

    @property
    def handedness(self) -> str:
        return self.raw.handedness


class LandmarkProcessor:
    """Converts a HandLandmarks object into a HandState."""

    def process(self, hand: HandLandmarks) -> HandState:
        lm = hand.landmarks
        state = HandState(raw=hand)

        state.thumb  = self._thumb_state(lm, hand.handedness)
        state.index  = self._finger_state(lm, INDEX_MCP, INDEX_PIP, INDEX_TIP)
        state.middle = self._finger_state(lm, MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP)
        state.ring   = self._finger_state(lm, RING_MCP, RING_PIP, RING_TIP)
        state.pinky  = self._finger_state(lm, PINKY_MCP, PINKY_PIP, PINKY_TIP)

        return state

    # ── Finger helpers ─────────────────────────────────────────────

    @staticmethod
    def _finger_state(
        lm: List[Tuple[float, float, float]],
        mcp: int, pip: int, tip: int,
    ) -> FingerState:
        """
        A finger is extended when its tip is significantly above (smaller y)
        its PIP joint.  curl_ratio = how much TIP y is above MCP y.
        """
        tip_y   = lm[tip][1]
        pip_y   = lm[pip][1]
        mcp_y   = lm[mcp][1]

        extended = tip_y < pip_y   # tip above PIP in normalised coords

        # curl_ratio: 0 = totally curled, 1 = fully straight
        span = mcp_y - (mcp_y - 0.2)  # normalise against a rough hand height
        curl = max(0.0, min(1.0, (mcp_y - tip_y) / max(span, 1e-6)))

        return FingerState(extended=extended, curl_ratio=curl)

    # Minimum displacement (normalised) for thumb tip vs IP joint.
    # Direction-based checks (tip_x < ip_x etc.) break when the camera
    # frame is flipped before MediaPipe — the handedness label gets
    # inverted so left/right logic fires in the wrong direction.
    # Using absolute distance on both axes avoids this entirely:
    #   horiz spread  → open palm / four distinction
    #   vert spread   → thumbs up / down
    _THUMB_MIN_EXTENSION: float = 0.04

    @staticmethod
    def _thumb_state(
        lm: List[Tuple[float, float, float]],
        handedness: str,
    ) -> FingerState:
        """
        Thumb extension via absolute displacement from IP joint.
        Works correctly for both hands on a horizontally-flipped frame.
        """
        tip_x = lm[THUMB_TIP][0]
        ip_x  = lm[THUMB_IP][0]
        tip_y = lm[THUMB_TIP][1]
        ip_y  = lm[THUMB_IP][1]
        mcp_x = lm[THUMB_MCP][0]

        thresh = LandmarkProcessor._THUMB_MIN_EXTENSION
        horiz = abs(tip_x - ip_x) > thresh   # sideways — open palm vs four
        vert  = abs(tip_y - ip_y) > thresh   # up/down — thumbs up/down
        extended = horiz or vert

        span  = abs(mcp_x - ip_x) + 1e-6
        curl  = max(0.0, min(1.0, abs(tip_x - ip_x) / span))
        return FingerState(extended=extended, curl_ratio=curl)


def distance(
    lm: List[Tuple[float, float, float]],
    a: int, b: int,
) -> float:
    """Euclidean distance between two landmarks (in normalised space)."""
    ax, ay = lm[a][0], lm[a][1]
    bx, by = lm[b][0], lm[b][1]
    return math.hypot(ax - bx, ay - by)
