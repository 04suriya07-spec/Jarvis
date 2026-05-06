"""
Javris Gesture — Vision Module: Camera Feed
─────────────────────────────────────────────
Real-time camera capture with MediaPipe Hand Landmarker (Tasks API 0.10+).

Runs in a background thread; communicates with the gesture engine
via a thread-safe queue.  Supports 1–2 hands simultaneously.

Model file:  data/models/hand_landmarker.task
  Auto-downloaded on first run if missing.
"""

from __future__ import annotations

import os
import queue
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    HandLandmarkerResult,
    RunningMode,
)
from mediapipe.tasks.python.components.containers import NormalizedLandmark

# ── Model path ────────────────────────────────────────────────────
_BASE_DIR = Path(__file__).parent.parent.parent   # S:/Javris
MODEL_PATH = _BASE_DIR / "data" / "models" / "hand_landmarker.task"
MODEL_URL  = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
)


def _ensure_model() -> Path:
    """Download the hand landmarker model if not present."""
    if not MODEL_PATH.exists():
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f"[CameraFeed] Downloading MediaPipe hand model → {MODEL_PATH}")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print(f"[CameraFeed] Model downloaded ({MODEL_PATH.stat().st_size // 1024} KB)")
    return MODEL_PATH


# ── MediaPipe drawing helper ──────────────────────────────────────
# The new Tasks API has no built-in draw_landmarks, so we draw manually.

HAND_CONNECTIONS = [
    (0,1),(1,2),(2,3),(3,4),          # thumb
    (0,5),(5,6),(6,7),(7,8),          # index
    (9,10),(10,11),(11,12),           # middle
    (0,9),(5,9),(9,13),               # palm knuckles
    (13,14),(14,15),(15,16),          # ring
    (0,17),(13,17),(17,18),(18,19),(19,20),  # pinky
]

def _draw_landmarks(
    frame: np.ndarray,
    landmarks: List[Tuple[float, float, float]],
    color_lm: Tuple = (0, 255, 100),
    color_conn: Tuple = (0, 180, 255),
) -> None:
    h, w = frame.shape[:2]
    pts = [(int(x * w), int(y * h)) for (x, y, _) in landmarks]
    for a, b in HAND_CONNECTIONS:
        cv2.line(frame, pts[a], pts[b], color_conn, 1, cv2.LINE_AA)
    for px, py in pts:
        cv2.circle(frame, (px, py), 4, color_lm, -1, cv2.LINE_AA)


# ── Data types ────────────────────────────────────────────────────

@dataclass
class HandLandmarks:
    """21 MediaPipe hand landmarks for a single detected hand."""
    landmarks: List[Tuple[float, float, float]]   # (x, y, z) — normalised [0,1]
    handedness: str                                 # "Left" | "Right"
    confidence: float = 1.0
    timestamp: float = field(default_factory=time.time)

    @property
    def wrist(self) -> Tuple[float, float, float]:
        return self.landmarks[0]

    def tip(self, finger: int) -> Tuple[float, float, float]:
        tips = [4, 8, 12, 16, 20]
        return self.landmarks[tips[finger]]


@dataclass
class CameraFrame:
    """One processed camera frame with all detected hands."""
    rgb_frame: np.ndarray
    bgr_frame: np.ndarray
    hands: List[HandLandmarks]
    width: int
    height: int
    timestamp: float = field(default_factory=time.time)
    fps: float = 0.0


# ── Camera Feed ───────────────────────────────────────────────────

class CameraFeed:
    """
    Captures frames from the camera and detects hand landmarks via
    MediaPipe Hand Landmarker (Tasks API — compatible with 0.10+).

    Usage::

        feed = CameraFeed()
        feed.start()

        while feed.running:
            frame = feed.get_frame(timeout=0.05)
            if frame:
                process(frame)

        feed.stop()
    """

    def __init__(
        self,
        camera_id: int = 0,
        width: int = 640,
        height: int = 480,
        target_fps: int = 30,
        max_hands: int = 1,
        detection_confidence: float = 0.5,
        tracking_confidence: float = 0.5,
    ):
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.max_hands = max_hands
        self.det_conf = detection_confidence
        self.trk_conf = tracking_confidence

        self._cap: Optional[cv2.VideoCapture] = None
        self._detector: Optional[HandLandmarker] = None
        self._thread: Optional[threading.Thread] = None
        self._frame_queue: queue.Queue[CameraFrame] = queue.Queue(maxsize=2)
        self._annotated_frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self.running = False
        self._fps_counter = _FPSCounter()

    # ── Public API ────────────────────────────────────────────────

    def start(self) -> bool:
        """Open camera and start background capture thread."""
        _ensure_model()

        # Build MediaPipe detector in VIDEO mode (synchronous, frame-by-frame)
        options = HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
            running_mode=RunningMode.VIDEO,
            num_hands=self.max_hands,
            min_hand_detection_confidence=self.det_conf,
            min_hand_presence_confidence=self.det_conf,
            min_tracking_confidence=self.trk_conf,
        )
        self._detector = HandLandmarker.create_from_options(options)

        self._cap = cv2.VideoCapture(self.camera_id)
        if not self._cap.isOpened():
            return False

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._cap.set(cv2.CAP_PROP_FPS, self.target_fps)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.running = True
        self._thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="CameraFeed"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self.running = False
        if self._thread:
            self._thread.join(timeout=3.0)
        if self._cap:
            self._cap.release()
        if self._detector:
            self._detector.close()

    def get_frame(self, timeout: float = 0.05) -> Optional[CameraFrame]:
        try:
            return self._frame_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_annotated_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return self._annotated_frame.copy() if self._annotated_frame is not None else None

    # ── Capture loop ──────────────────────────────────────────────

    def _capture_loop(self) -> None:
        frame_ms = 0
        while self.running:
            ret, bgr = self._cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            bgr = cv2.flip(bgr, 1)   # mirror
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            fps = self._fps_counter.tick()

            # MediaPipe Tasks API — VIDEO mode requires monotonic timestamp_ms
            frame_ms += int(1000 / max(fps, 1)) if fps > 0 else 33
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            try:
                result: HandLandmarkerResult = self._detector.detect_for_video(
                    mp_image, frame_ms
                )
            except Exception:
                result = None

            hands: List[HandLandmarks] = []
            annotated = bgr.copy()

            if result and result.hand_landmarks:
                for lm_list, handedness_list in zip(
                    result.hand_landmarks, result.handedness
                ):
                    label = handedness_list[0].display_name  # "Left" | "Right"
                    score = handedness_list[0].score
                    landmarks = [(lm.x, lm.y, lm.z) for lm in lm_list]

                    _draw_landmarks(annotated, landmarks)
                    hands.append(HandLandmarks(
                        landmarks=landmarks,
                        handedness=label,
                        confidence=score,
                    ))

            h, w = bgr.shape[:2]
            frame = CameraFrame(
                rgb_frame=rgb, bgr_frame=bgr,
                hands=hands, width=w, height=h, fps=fps,
            )

            with self._lock:
                self._annotated_frame = annotated

            if self._frame_queue.full():
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    pass
            self._frame_queue.put_nowait(frame)


# ── FPS counter ───────────────────────────────────────────────────

class _FPSCounter:
    def __init__(self, window: int = 30):
        self._times: list = []
        self._window = window

    def tick(self) -> float:
        now = time.time()
        self._times.append(now)
        if len(self._times) > self._window:
            self._times.pop(0)
        if len(self._times) < 2:
            return 30.0
        return (len(self._times) - 1) / (self._times[-1] - self._times[0])
