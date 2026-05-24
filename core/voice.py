"""
Javris Voice Module
───────────────────
STT:  Whisper (local) | Whisper API | Google Speech
TTS:  ElevenLabs | edge-tts (Microsoft Neural) | pyttsx3 (offline)

Usage:
    voice = VoiceEngine()
    await voice.init()
    text = await voice.listen()          # returns transcribed string
    await voice.speak("Hello, world!")   # plays audio
"""

from __future__ import annotations

import asyncio
import io
import os
import queue
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.voice")
cfg = get_config()


# ─── Speech-to-Text ──────────────────────────────────────────────────────────

class WhisperSTT:
    """Local Whisper model for transcription."""

    def __init__(self, model_name: str = "base"):
        self._model = None
        self._model_name = model_name

    def load(self) -> None:
        try:
            import whisper
            logger.info(f"Loading Whisper model: {self._model_name}")
            self._model = whisper.load_model(self._model_name)
            logger.info("Whisper model loaded.")
        except ImportError:
            logger.warning("openai-whisper not installed. STT will be disabled.")

    def transcribe(self, audio_path: str) -> str:
        if self._model is None:
            return ""
        result = self._model.transcribe(audio_path, fp16=False)
        return result.get("text", "").strip()


class MicrophoneCapture:
    """Captures audio using sounddevice with dynamic silence detection (VAD)."""

    def __init__(self, silence_timeout: float = 1.0, sample_rate: int = 16000):
        self.silence_timeout = silence_timeout
        self.sample_rate = sample_rate
        self.energy_threshold = 500  # Voice threshold

    def record(self) -> bytes | None:
        """Records until silence is detected, with warm-up beep."""
        import sounddevice as sd
        import numpy as np
        import speech_recognition as sr
        import time
        import os

        # 1. Beep to signal listening
        if os.name == "nt":
            import winsound
            winsound.Beep(800, 150)

        logger.debug("Listening (Patient VAD)...")
        recorded_chunks = []
        silence_start = None
        has_started_speaking = False
        
        def callback(indata, frames, time_info, status):
            recorded_chunks.append(indata.copy())

        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='int16', callback=callback):
            start_time = time.time()
            while True:
                if not recorded_chunks:
                    if time.time() - start_time > 4: # Wait 4s for first sound
                        return None
                    time.sleep(0.1)
                    continue

                # Get energy of last 3 chunks for stability
                recent = recorded_chunks[-3:]
                latest_chunk = np.concatenate(recent)
                energy = np.sqrt(np.mean(latest_chunk.astype(float)**2))
                
                # Check if speaking has started
                if energy > self.energy_threshold:
                    has_started_speaking = True
                    silence_start = None
                
                # If we've started, look for silence
                if has_started_speaking:
                    if energy < self.energy_threshold:
                        if silence_start is None:
                            silence_start = time.time()
                        elif time.time() - silence_start > self.silence_timeout:
                            break # Silence met
                    else:
                        silence_start = None
                else:
                    # Haven't started yet - check for initial timeout
                    if time.time() - start_time > 4.0:
                        return None

                if time.time() - start_time > 15: # Max record limit
                    break
                
                time.sleep(0.1)

        if not recorded_chunks or not has_started_speaking:
            return None
            
        full_audio = np.concatenate(recorded_chunks)
        audio_data = sr.AudioData(full_audio.tobytes(), self.sample_rate, 2)
        return audio_data.get_wav_data()

    def transcribe_google(self, wav_bytes: bytes) -> str:
        try:
            import speech_recognition as sr
            recognizer = sr.Recognizer()
            audio = sr.AudioData(wav_bytes, self.sample_rate, 2)
            # Use a slightly longer timeout for Google
            return recognizer.recognize_google(audio)
        except Exception as e:
            logger.warning(f"Google STT failed: {e}")
            return ""


# ─── Text-to-Speech ───────────────────────────────────────────────────────────

class EdgeTTS:
    """Microsoft Edge TTS (free, neural, no API key needed)."""

    DEFAULT_VOICE = "en-GB-RyanNeural"

    async def synthesize(self, text: str, voice: str = DEFAULT_VOICE) -> bytes:
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            audio_bytes = b""
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_bytes += chunk["data"]
            return audio_bytes
        except Exception as e:
            logger.error(f"EdgeTTS error: {e}")
            return b""


class ElevenLabsTTS:
    """ElevenLabs neural TTS."""

    def __init__(self, api_key: str, voice_id: str):
        self.api_key = api_key
        self.voice_id = voice_id

    async def synthesize(self, text: str) -> bytes:
        try:
            from elevenlabs.client import AsyncElevenLabs
            client = AsyncElevenLabs(api_key=self.api_key)
            audio = b""
            async for chunk in await client.text_to_speech.convert(
                voice_id=self.voice_id,
                text=text,
                model_id="eleven_turbo_v2",
            ):
                audio += chunk
            return audio
        except Exception as e:
            logger.error(f"ElevenLabs error: {e}")
            return b""


class Pyttsx3TTS:
    """Fully offline pyttsx3 TTS."""

    def synthesize_and_play(self, text: str) -> None:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 175)
            engine.setProperty("volume", 0.9)
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            logger.error(f"pyttsx3 error: {e}")


def _play_audio_bytes(audio_bytes: bytes) -> None:
    """Play MP3/WAV bytes using sounddevice or system player."""
    logger.info(f"Audio playback triggered. Size: {len(audio_bytes)} bytes")
    try:
        import sounddevice as sd
        import soundfile as sf
        import io
        buf = io.BytesIO(audio_bytes)
        data, samplerate = sf.read(buf)
        logger.info(f"Direct playback via sounddevice ({samplerate}Hz)")
        sd.play(data, samplerate)
        sd.wait()
    except Exception as e:
        logger.debug(f"Direct playback skipped (likely MP3): {e}")
        # Fallback: write to temp file and open
        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(audio_bytes)
                tmp = os.path.abspath(f.name)
            
            logger.info(f"Fallback playback via OS: {tmp}")
            if os.name == "nt":
                try:
                    from playsound import playsound
                    playsound(tmp)
                except Exception as pe:
                    logger.warning(f"playsound failed: {pe}. Trying os.startfile.")
                    os.startfile(tmp)
            else:
                # Linux: try fast players in order
                for player in ["mpg123", "mpv", "aplay", "paplay"]:
                    if os.system(f"which {player} > /dev/null 2>&1") == 0:
                        os.system(f"{player} -q {tmp} 2>/dev/null")
                        break
            
            # Use a slightly longer sleep to let playback finish
            time.sleep(len(audio_bytes) / 15000 + 1)
            
            try:
                os.unlink(tmp)
            except OSError:
                pass
        except Exception as e:
            logger.error(f"Audio playback failed: {e}")


# ─── Unified Voice Engine ─────────────────────────────────────────────────────

class VoiceEngine:
    """
    Single entry-point for all voice operations.
    Call `init()` once, then use `listen()` and `speak()`.
    """

    def __init__(self):
        self._stt: WhisperSTT | None = None
        self._mic = MicrophoneCapture(silence_timeout=2.0)
        self._edge_tts = EdgeTTS()
        self._eleven_tts: ElevenLabsTTS | None = None
        self._pyttsx3 = Pyttsx3TTS()
        self._listening = False
        self._wake_word = cfg.wake_word.lower()

    async def init(self) -> None:
        """Load STT model and configure TTS."""
        if cfg.stt_engine == "whisper_local":
            self._stt = WhisperSTT(cfg.whisper_model)
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._stt.load)

        if cfg.tts_engine == "elevenlabs" and cfg.elevenlabs_api_key:
            self._eleven_tts = ElevenLabsTTS(
                cfg.elevenlabs_api_key, cfg.elevenlabs_voice_id
            )

        logger.info(f"VoiceEngine ready | STT={cfg.stt_engine} TTS={cfg.tts_engine}")

    async def listen(self) -> str:
        """Record from microphone and return transcribed text."""
        loop = asyncio.get_running_loop()
        wav_bytes = await loop.run_in_executor(None, self._mic.record)
        if not wav_bytes:
            return ""

        if cfg.stt_engine == "google":
            return await loop.run_in_executor(
                None, self._mic.transcribe_google, wav_bytes
            )
        elif self._stt:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                tmp = f.name
            text = await loop.run_in_executor(None, self._stt.transcribe, tmp)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return text

        return ""

    async def speak(self, text: str) -> None:
        """Synthesize and play speech."""
        if not text.strip():
            return

        logger.debug(f"Speaking: {text[:80]}...")

        if cfg.tts_engine == "pyttsx3":
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._pyttsx3.synthesize_and_play, text)
            return

        if cfg.tts_engine == "elevenlabs" and self._eleven_tts:
            audio = await self._eleven_tts.synthesize(text)
        else:
            audio = await self._edge_tts.synthesize(text)

        if audio:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _play_audio_bytes, audio)

    async def listen_once(self) -> str:
        """
        Single-shot listen: record one utterance and return the transcribed text.
        Used by the gesture bridge to handle voice-activated gestures.
        """
        return await self.listen()

    async def listen_for_wake_word(self) -> bool:
        """Listen and return True when wake word is detected."""
        text = await self.listen()
        detected = self._wake_word in text.lower()
        if detected:
            logger.info(f"Wake word '{self._wake_word}' detected!")
        return detected

    async def interactive_loop(self, callback) -> None:
        """
        Continuous voice loop.
        callback(text) is called with each transcribed utterance.
        """
        logger.info(f"Voice loop started. Say '{self._wake_word}' to activate.")
        while True:
            try:
                text = await self.listen()
                if text and self._wake_word in text.lower():
                    # Strip wake word from command
                    command = text.lower().replace(self._wake_word, "").strip()
                    if command:
                        await callback(command)
                    else:
                        await self.speak("Yes? How can I help?")
                        command = await self.listen()
                        if command:
                            await callback(command)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Voice loop error: {e}")
                await asyncio.sleep(1)
