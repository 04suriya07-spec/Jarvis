"""
core/gemini_live.py
───────────────────
Gemini Multimodal Live API — real-time audio + optional video streaming.

Uses the google-genai SDK to open a persistent WebSocket session with
Gemini. Audio flows from microphone → Gemini → speaker at native quality
with no STT/TTS pipeline in the middle — lowest possible latency.

Modes
─────
  GeminiLiveSession(mode="audio")        — voice-only
  GeminiLiveSession(mode="video")        — voice + webcam frames

Usage
─────
    session = GeminiLiveSession(api_key=..., system_prompt=...)
    await session.run()          # blocks until user presses Ctrl-C

    # Or one-shot turn:
    reply_text = await session.send_text("What's 2 + 2?")

Requirements
────────────
    pip install google-genai pyaudio opencv-python

Audio specs
───────────
  Input  (mic → Gemini): PCM 16-bit signed, 16 kHz, mono, little-endian
  Output (Gemini → speaker): PCM 16-bit signed, 24 kHz, mono, little-endian
"""

from __future__ import annotations

import asyncio
import base64
import threading
from typing import Literal, Optional

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.gemini_live")
cfg = get_config()

# ── Audio constants ────────────────────────────────────────────────────────────

MIC_SAMPLE_RATE   = 16_000   # Hz  – Gemini input spec
SPK_SAMPLE_RATE   = 24_000   # Hz  – Gemini output spec
CHANNELS          = 1
CHUNK_SIZE        = 1_024    # frames per read (~64 ms at 16 kHz)
DTYPE             = "int16"  # sounddevice dtype (replaces pyaudio.paInt16)

# ── Video constants ────────────────────────────────────────────────────────────

VIDEO_FPS         = 0.5      # frames per second to send (1 frame every 2s)
VIDEO_WIDTH       = 640
VIDEO_HEIGHT      = 480
JPEG_QUALITY      = 75       # 0–100

# ── Gemini model ───────────────────────────────────────────────────────────────

LIVE_MODEL = "models/gemini-2.5-flash"


# ─────────────────────────────────────────────────────────────────────────────
# GeminiLiveSession
# ─────────────────────────────────────────────────────────────────────────────

class GeminiLiveSession:
    """
    Manages a full-duplex Gemini Live session.

    Parameters
    ----------
    api_key       : Google AI API key (defaults to GOOGLE_API_KEY env var)
    system_prompt : Persona / instructions sent as system instruction
    mode          : "audio" (default) or "video" (adds webcam frames)
    voice         : Gemini voice name — Puck | Charon | Kore | Fenrir | Aoede
    model         : Override the default Live model
    """

    def __init__(
        self,
        api_key: str = "",
        system_prompt: str = "You are Jarvis, a helpful AI assistant.",
        mode: Literal["audio", "video"] = "audio",
        voice: str = "Puck",
        model: str = LIVE_MODEL,
    ):
        # Build key pool from all configured keys (rotate on failure)
        candidate_keys = [
            cfg.google_api_key_1,
            cfg.google_api_key_2,
            cfg.google_api_key_3,
            cfg.google_api_key,
        ]
        pool_keys = [k for k in candidate_keys if k]
        # Deduplicate
        seen: set[str] = set()
        pool_keys = [k for k in pool_keys if not (k in seen or seen.add(k))]

        if api_key:
            self._api_key = api_key
            self._key_pool = [api_key]
        elif pool_keys:
            self._api_key = pool_keys[0]
            self._key_pool = pool_keys
        else:
            raise ValueError(
                "Gemini API key required. Set GOOGLE_API_KEY_1 in .env "
                "or pass api_key= to GeminiLiveSession()."
            )

        self._key_idx = 0

        self._system_prompt = system_prompt
        self._mode = mode
        self._voice = voice
        self._model = model

        # Internal state
        self._stop_event = asyncio.Event()
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._video_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
        self._response_texts: list[str] = []

    # ── Key rotation ──────────────────────────────────────────────────────────

    def _next_key(self) -> str:
        """Rotate to the next key in the pool and return it."""
        self._key_idx = (self._key_idx + 1) % len(self._key_pool)
        self._api_key = self._key_pool[self._key_idx]
        logger.warning(
            f"Gemini Live: rotating to key slot {self._key_idx + 1}/{len(self._key_pool)}"
        )
        return self._api_key

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """
        Start the interactive live session.
        Rotates to the next API key on quota errors before giving up.
        Runs until Ctrl-C or stop() is called.
        """
        logger.info(f"Starting Gemini Live session | mode={self._mode} voice={self._voice}")
        print(f"\n[Gemini Live] Connected. Speak into your microphone. (Ctrl-C to stop)\n")

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError(
                "google-genai not installed. Run: pip install google-genai"
            )

        try:
            import sounddevice as sd
        except ImportError:
            raise ImportError("sounddevice not installed. Run: pip install sounddevice")

        last_exc: Optional[Exception] = None
        for attempt in range(len(self._key_pool)):
            try:
                client = genai.Client(api_key=self._api_key)

                config = types.LiveConnectConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=self._voice
                            )
                        )
                    ),
                    system_instruction=types.Content(
                        parts=[types.Part(text=self._system_prompt)]
                    ),
                )

                async with client.aio.live.connect(model=self._model, config=config) as session:
                    await asyncio.gather(
                        self._capture_audio(sd),
                        self._capture_video() if self._mode == "video" else self._noop(),
                        self._send_loop(session),
                        self._receive_loop(session, sd),
                    )
                return  # clean exit

            except Exception as exc:
                last_exc = exc
                err_str = str(exc).lower()
                if "quota" in err_str or "resource_exhausted" in err_str or "429" in err_str:
                    if attempt + 1 < len(self._key_pool):
                        self._next_key()
                        continue
                raise

        if last_exc:
            raise last_exc

    async def stop(self) -> None:
        """Signal the session to stop cleanly."""
        self._stop_event.set()

    async def send_text(self, text: str) -> str:
        """
        Send a single text message and return the text response.
        Rotates keys on quota errors.
        """
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError("google-genai not installed. Run: pip install google-genai")

        last_exc: Optional[Exception] = None
        for attempt in range(len(self._key_pool)):
            try:
                client = genai.Client(api_key=self._api_key)
                config = types.LiveConnectConfig(
                    response_modalities=["TEXT"],
                    system_instruction=types.Content(
                        parts=[types.Part(text=self._system_prompt)]
                    ),
                )
                async with client.aio.live.connect(model=self._model, config=config) as session:
                    await session.send(input=text, end_of_turn=True)
                    parts = []
                    async for response in session.receive():
                        if response.text:
                            parts.append(response.text)
                        if hasattr(response, "server_content") and response.server_content:
                            if response.server_content.turn_complete:
                                break
                    return "".join(parts)
            except Exception as exc:
                last_exc = exc
                err_str = str(exc).lower()
                if ("quota" in err_str or "resource_exhausted" in err_str or "429" in err_str) \
                        and attempt + 1 < len(self._key_pool):
                    self._next_key()
                    continue
                raise

        if last_exc:
            raise last_exc
        return ""

    # ── Audio capture ─────────────────────────────────────────────────────────

    async def _capture_audio(self, sd) -> None:
        """Read microphone via sounddevice and push PCM chunks to _audio_queue."""
        loop = asyncio.get_event_loop()
        logger.debug("Microphone stream opened (sounddevice)")

        def _mic_callback(indata, frames, time_info, status):
            # indata is a numpy array — convert to raw bytes
            loop.call_soon_threadsafe(
                self._audio_queue.put_nowait, indata.tobytes()
            )

        stream = sd.InputStream(
            samplerate=MIC_SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_SIZE,
            callback=_mic_callback,
        )
        with stream:
            await self._stop_event.wait()

        logger.debug("Microphone stream closed")

    # ── Video capture ─────────────────────────────────────────────────────────

    async def _capture_video(self) -> None:
        """Capture webcam frames and push JPEG bytes to _video_queue."""
        try:
            import cv2
        except ImportError:
            logger.warning("opencv-python not installed — video capture disabled")
            return

        loop = asyncio.get_event_loop()
        interval = 1.0 / VIDEO_FPS

        cap = await loop.run_in_executor(None, cv2.VideoCapture, 0)
        if not cap.isOpened():
            logger.warning("Webcam not available — video capture disabled")
            return

        logger.debug("Webcam stream opened")
        try:
            while not self._stop_event.is_set():
                ret, frame = await loop.run_in_executor(None, cap.read)
                if not ret:
                    break

                frame = await loop.run_in_executor(
                    None,
                    lambda f=frame: cv2.resize(f, (VIDEO_WIDTH, VIDEO_HEIGHT)),
                )
                ok, buf = await loop.run_in_executor(
                    None,
                    lambda f=frame: cv2.imencode(
                        ".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
                    ),
                )
                if ok:
                    try:
                        self._video_queue.put_nowait(buf.tobytes())
                    except asyncio.QueueFull:
                        pass  # drop frame — queue full means we're keeping up

                await asyncio.sleep(interval)
        finally:
            await loop.run_in_executor(None, cap.release)
            logger.debug("Webcam stream closed")

    # ── Send loop ─────────────────────────────────────────────────────────────

    async def _send_loop(self, session) -> None:
        """Drain audio (and video) queues and forward to Gemini."""
        try:
            from google.genai import types
        except ImportError:
            return

        video_interval = 1.0 / VIDEO_FPS
        last_video_send = 0.0

        while not self._stop_event.is_set():
            # Collect up to 8 audio chunks per iteration for efficiency
            chunks = []
            try:
                for _ in range(8):
                    chunks.append(self._audio_queue.get_nowait())
            except asyncio.QueueEmpty:
                pass

            if not chunks:
                await asyncio.sleep(0.01)
                continue

            audio_blob = types.Blob(
                mime_type=f"audio/pcm;rate={MIC_SAMPLE_RATE}",
                data=b"".join(chunks),
            )
            blobs = [audio_blob]

            # Interleave video if mode=video and queue has a frame
            now = asyncio.get_event_loop().time()
            if self._mode == "video" and (now - last_video_send) >= video_interval:
                try:
                    jpeg = self._video_queue.get_nowait()
                    blobs.append(types.Blob(mime_type="image/jpeg", data=jpeg))
                    last_video_send = now
                except asyncio.QueueEmpty:
                    pass

            await session.send(
                input=types.LiveClientRealtimeInput(media_chunks=blobs)
            )

    # ── Receive loop ──────────────────────────────────────────────────────────

    async def _receive_loop(self, session, sd) -> None:
        """Receive Gemini audio responses and play them via sounddevice."""
        import numpy as np
        loop = asyncio.get_event_loop()
        logger.debug("Speaker stream opened (sounddevice)")

        speaker = sd.OutputStream(
            samplerate=SPK_SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_SIZE,
        )
        speaker.start()

        try:
            async for response in session.receive():
                if self._stop_event.is_set():
                    break

                # Audio response — convert bytes → numpy and play
                if response.data:
                    audio_np = np.frombuffer(response.data, dtype=np.int16)
                    await loop.run_in_executor(None, speaker.write, audio_np)

                # Text transcript
                if response.text:
                    logger.info(f"[Gemini] {response.text}")
                    print(f"\n[Jarvis] {response.text}")
                    self._response_texts.append(response.text)

                if hasattr(response, "server_content") and response.server_content:
                    if response.server_content.turn_complete:
                        logger.debug("Gemini turn complete")

        finally:
            speaker.stop()
            speaker.close()
            logger.debug("Speaker stream closed")

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _noop(self) -> None:
        """Placeholder coroutine when video mode is off."""
        await self._stop_event.wait()


# ─────────────────────────────────────────────────────────────────────────────
# Convenience entry-point
# ─────────────────────────────────────────────────────────────────────────────

async def start_live_session(
    mode: Literal["audio", "video"] = "audio",
    voice: str = "Puck",
    system_prompt: str = (
        "You are Jarvis, a brilliant and concise AI assistant. "
        "Respond naturally and conversationally."
    ),
) -> None:
    """
    Quick-start helper — call from main.py or CLI.

    Example
    -------
        import asyncio
        from core.gemini_live import start_live_session
        asyncio.run(start_live_session(mode="video"))
    """
    session = GeminiLiveSession(
        system_prompt=system_prompt,
        mode=mode,
        voice=voice,
    )
    try:
        await session.run()
    except KeyboardInterrupt:
        print("\n[Gemini Live] Session ended.")
    finally:
        await session.stop()
