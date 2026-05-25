"""
core/wake_word.py
──────────────────
Continuous background wake-word detection using Picovoice Porcupine.
Requires PORCUPINE_ACCESS_KEY in .env
"""

import os
import struct
import asyncio
import threading
from typing import Callable, Optional
from core.logger import get_logger
from core.config import get_config
import numpy as np

logger = get_logger("javris.wake_word")
cfg = get_config()

class WakeWordDetector:
    def __init__(self, callback: Callable):
        self.callback = callback
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        access_key = os.getenv("PORCUPINE_ACCESS_KEY")
        if access_key:
            try:
                import pvporcupine
                import pyaudio
                self._stop_event.clear()
                self._thread = threading.Thread(target=self._run_picovoice, args=(access_key, pvporcupine, pyaudio), daemon=True)
                self._thread.start()
                logger.info("Wake word detection started (Picovoice).")
                return
            except ImportError:
                logger.warning("Picovoice requested but pvporcupine/pyaudio not installed.")

        try:
            import openwakeword
            from openwakeword.model import Model
            import pyaudio
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_openwakeword, args=(Model, pyaudio), daemon=True)
            self._thread.start()
            logger.info("Wake word detection started (OpenWakeWord - Free/Local).")
            return
        except ImportError:
            logger.warning("OpenWakeWord not installed. Run: pip install openwakeword")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            logger.info("Wake word detection stopped.")

    def _run_openwakeword(self, Model, pyaudio):
        try:
            # Initialize openwakeword with 'jarvis' model
            # Note: openwakeword has a 'alexa', 'hey_google', but you can use 'hey_jarvis' or 'jarvis'
            oww_model = Model(wakeword_models=["jarvis"], inference_framework="tflite")
            
            pa = pyaudio.PyAudio()
            audio_stream = pa.open(
                rate=16000,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=1280
            )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            while not self._stop_event.is_set():
                pcm = audio_stream.read(1280, exception_on_overflow=False)
                audio_frame = np.frombuffer(pcm, dtype=np.int16)
                
                # Process with openwakeword
                prediction = oww_model.predict(audio_frame)
                
                # Check for 'jarvis' model detection
                if any(v > 0.5 for v in prediction.values()):
                    logger.info("OpenWakeWord: Wake word detected!")
                    try:
                        loop.run_until_complete(self.callback())
                    except Exception as e:
                        logger.error(f"Error in wake word callback: {e}")

        except Exception as e:
            logger.error(f"OpenWakeWord engine error: {e}")
        finally:
            if 'audio_stream' in locals(): audio_stream.close()
            if 'pa' in locals(): pa.terminate()

    def _run_picovoice(self, access_key, pvporcupine, pyaudio):
        porcupine = None
        pa = None
        audio_stream = None
        try:
            keywords = ["jarvis"]
            try:
                porcupine = pvporcupine.create(access_key=access_key, keywords=keywords)
            except ValueError:
                porcupine = pvporcupine.create(access_key=access_key, keywords=["porcupine"])

            pa = pyaudio.PyAudio()
            audio_stream = pa.open(
                rate=porcupine.sample_rate,
                channels=1,
                format=pyaudio.paInt16,
                input=True,
                frames_per_buffer=porcupine.frame_length
            )

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            while not self._stop_event.is_set():
                pcm = audio_stream.read(porcupine.frame_length, exception_on_overflow=False)
                audio_frame = struct.unpack_from("h" * porcupine.frame_length, pcm)

                result = porcupine.process(audio_frame)
                if result >= 0:
                    logger.info("Picovoice: Wake word detected!")
                    try:
                        loop.run_until_complete(self.callback())
                    except Exception as e:
                        logger.error(f"Error in wake word callback: {e}")
        except Exception as e:
            logger.error(f"Picovoice engine error: {e}")
        finally:
            if audio_stream: audio_stream.close()
            if pa: pa.terminate()
            if porcupine: porcupine.delete()
