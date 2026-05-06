"""
Javris Always-On Wake Word Daemon  v2
══════════════════════════════════════
Keeps microphone open in the background.
Triggers full Whisper transcription only when wake word is detected.

Detection strategy (in priority order):
  1. Picovoice Porcupine  — 100ms latency, runs on-device, free tier
     Requires: pip install pvporcupine  +  PORCUPINE_API_KEY in .env
  2. Energy-threshold keyword scan  — pure Python fallback, ~1.5s latency
     Requires: sounddevice + numpy (already in requirements)

After wake word detected:
  → Records 5-second audio clip
  → Sends to Javris server /api/voice/listen_once  (which runs Whisper)
  → Speaks the reply via TTS

Run:  python ui/wake_daemon.py
"""

from __future__ import annotations

import argparse
import os
import platform
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import httpx
import numpy as np

# ── Config ────────────────────────────────────────────────────────

JAVRIS_API       = os.getenv("JAVRIS_API", "http://localhost:8000")
LISTEN_ONCE_URL  = f"{JAVRIS_API}/api/voice/listen_once"
SPEAK_URL        = f"{JAVRIS_API}/api/voice/speak"
PORCUPINE_KEY    = os.getenv("PORCUPINE_API_KEY", "")
SAMPLE_RATE      = 16_000
FRAME_LENGTH     = 512          # Porcupine default
RECORD_SECS      = 5            # seconds to record after wakeword
ENERGY_THRESHOLD = 800          # RMS threshold for energy detector
KEYWORD          = "jarvis"     # keyword to match in energy mode

_running = True


# ── Notification helper ───────────────────────────────────────────

def notify(title: str, body: str, duration_ms: int = 3000):
    OS = platform.system()
    try:
        if OS == "Linux":
            subprocess.run(
                ["notify-send", "-t", str(duration_ms), title, body],
                check=False, capture_output=True,
            )
        elif OS == "Darwin":
            subprocess.run(
                ["osascript", "-e",
                 f'display notification "{body}" with title "{title}"'],
                check=False,
            )
        elif OS == "Windows":
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$n = New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon = [System.Drawing.SystemIcons]::Information;"
                "$n.Visible = $true;"
                f'$n.ShowBalloonTip({duration_ms}, "{title}", "{body}", '
                f'[System.Windows.Forms.ToolTipIcon]::Info);'
                "Start-Sleep -Milliseconds 500;"
                "$n.Dispose();"
            )
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                creationflags=0x08000000,
            )
    except Exception:
        pass
    print(f"[notify] {title}: {body}")


# ── Server interaction ────────────────────────────────────────────

def trigger_listen_once() -> tuple[str, str]:
    """
    Tell the Javris server to do one listen→AI→speak cycle.
    Returns (transcript, reply).
    """
    try:
        resp = httpx.post(LISTEN_ONCE_URL, timeout=45)
        if resp.status_code == 200:
            data     = resp.json()
            transcript = data.get("transcript", "")
            reply      = data.get("reply", "")
            return transcript, reply
        else:
            print(f"[wake] Server returned {resp.status_code}")
            return "", ""
    except httpx.ConnectError:
        notify("Javris", "Server not running — start with: python main.py serve")
        return "", ""
    except Exception as e:
        print(f"[wake] Error: {e}")
        return "", ""


def wait_for_server(max_wait: int = 60):
    """Block until the Javris server is reachable."""
    print("[wake] Waiting for Javris server…")
    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            httpx.get(f"{JAVRIS_API}/api/status", timeout=2)
            print("[wake] Server online ✓")
            return True
        except Exception:
            time.sleep(2)
    print("[wake] Server not reachable — continuing anyway")
    return False


# ═══════════════════════════════════════════════════════════════════
#  Strategy 1 — Picovoice Porcupine
# ═══════════════════════════════════════════════════════════════════

def run_porcupine():
    """
    Always-on wake word detection via Porcupine.
    Falls back to energy detector if not available.
    """
    import pvporcupine
    import sounddevice as sd

    print("[wake] Porcupine engine starting…")
    porcupine = pvporcupine.create(
        access_key=PORCUPINE_KEY,
        keywords=["jarvis"],
    )
    print(f"[wake] Porcupine ready | frame_length={porcupine.frame_length} | sr={porcupine.sample_rate}")
    notify("Javris", "Always-on listening active (Porcupine)")

    frame_buf = np.zeros(porcupine.frame_length, dtype=np.int16)
    frame_idx  = 0

    def callback(indata, frames, time_info, status):
        nonlocal frame_idx
        global _running
        if not _running:
            raise sd.CallbackStop()
        pcm = (indata[:, 0] * 32768).astype(np.int16)
        for sample in pcm:
            frame_buf[frame_idx] = sample
            frame_idx += 1
            if frame_idx == porcupine.frame_length:
                frame_idx = 0
                result     = porcupine.process(frame_buf)
                if result >= 0:
                    print("[wake] 🔊 Wake word detected!")
                    notify("Javris", "Listening…")
                    _handle_wakeword()

    with sd.InputStream(
        samplerate=porcupine.sample_rate,
        channels=1,
        dtype="float32",
        blocksize=porcupine.frame_length,
        callback=callback,
    ):
        while _running:
            time.sleep(0.1)

    porcupine.delete()


def _handle_wakeword():
    """Called when wake word fires. Offload to thread to keep audio loop running."""
    threading.Thread(target=_do_listen_cycle, daemon=True).start()


def _do_listen_cycle():
    """Sends listen request to server and shows result."""
    print("[wake] 👂 Waiting for command...")
    transcript, reply = trigger_listen_once()
    if transcript:
        msg = f"You: {transcript}"
        if reply:
            msg += f"\nJavris: {reply[:120]}"
        notify("Javris", msg, 7000)
        print(f"[wake] You: {transcript}")
        print(f"[wake] Javris: {reply[:120]}")
    else:
        print("[wake] No speech detected")


# ═══════════════════════════════════════════════════════════════════
#  Strategy 2 — Energy-threshold keyword detector (no key required)
# ═══════════════════════════════════════════════════════════════════

import queue

import queue

import queue
import threading

mic_free_event = threading.Event()
mic_free_event.set() # Mic is free initially

def run_energy_detector():
    """
    Intelligent Energy-Gated Wake Word with Mic Locking.
    """
    import speech_recognition as sr
    import sounddevice as sd
    import numpy as np

    print("[wake] Initializing High-Sensitivity Stream...")
    r = sr.Recognizer()
    audio_queue = queue.Queue()

    def callback(indata, frames, time, status):
        if mic_free_event.is_set():
            audio_queue.put(indata.copy())

    # User-tunable threshold
    energy_threshold = 500 
    silence_counter = 0
    is_speaking = False
    speech_buffer = []

    print(f"[wake] Listening for '{KEYWORD.upper()}'... (Sensitivity: HIGH)")
    notify("Javris", f"Voice ears active. Say '{KEYWORD}'")

    while _running:
        # Wait for mic to be free before starting stream
        mic_free_event.wait()
        
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16', callback=callback):
            while _running and mic_free_event.is_set():
                # Consume queue
                while not audio_queue.empty():
                    chunk = audio_queue.get()
                    rms = np.sqrt(np.mean(chunk.astype(float)**2))

                    if rms > energy_threshold:
                        if not is_speaking:
                            print("[wake] 🔊 Audio detected, identifying...")
                            is_speaking = True
                        speech_buffer.append(chunk)
                        silence_counter = 0
                    elif is_speaking:
                        speech_buffer.append(chunk)
                        silence_counter += 1
                        
                        # If silence lasts for ~0.8s, process the burst
                        if silence_counter > (SAMPLE_RATE / FRAME_LENGTH * 0.8):
                            is_speaking = False
                            full_burst = np.concatenate(speech_buffer)
                            speech_buffer = []
                            
                            def _stt_check(audio_bytes):
                                try:
                                    audio_data = sr.AudioData(audio_bytes, SAMPLE_RATE, 2)
                                    text = r.recognize_google(audio_data, language="en-US").lower()
                                    print(f"[wake] Heard: '{text}'")
                                    # Fuzzy match variants
                                    variants = [KEYWORD, "travis", "service", "java", "drivers", "assistant"]
                                    if any(v in text for v in variants):
                                        print(f"[wake] ⭐ MATCH! (Variant: {text})")
                                        # LOCK MIC and trigger cycle
                                        mic_free_event.clear()
                                        _do_listen_cycle_locked()
                                except: pass

                            threading.Thread(target=_stt_check, args=(full_burst.tobytes(),), daemon=True).start()

                time.sleep(0.05)
        
        # If we exited the stream because mic_free_event was cleared
        # we just wait here for it to be reset by the cycle end.
        time.sleep(0.5)

def _do_listen_cycle_locked():
    """Special cycle that releases lock when done."""
    try:
        _do_listen_cycle()
    finally:
        print("[wake] Command cycle finished. Resuming ears...")
        mic_free_event.set()


# ═══════════════════════════════════════════════════════════════════
#  Entry point
# ═══════════════════════════════════════════════════════════════════

def main():
    global _running, PORCUPINE_KEY, JAVRIS_API, LISTEN_ONCE_URL, SPEAK_URL

    # Load .env if present
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
        PORCUPINE_KEY = os.getenv("PORCUPINE_API_KEY", "")

    parser = argparse.ArgumentParser(description="Javris Always-On Wake Daemon")
    parser.add_argument(
        "--engine",
        choices=["porcupine", "energy", "auto"],
        default="auto",
        help="Wake word engine to use (default: auto)",
    )
    parser.add_argument(
        "--api",
        default=JAVRIS_API,
        help=f"Javris server URL (default: {JAVRIS_API})",
    )
    args = parser.parse_args()

    JAVRIS_API      = args.api
    LISTEN_ONCE_URL = f"{JAVRIS_API}/api/voice/listen_once"
    SPEAK_URL       = f"{JAVRIS_API}/api/voice/speak"

    wait_for_server(max_wait=30)

    engine = args.engine
    if engine == "auto":
        engine = "porcupine" if PORCUPINE_KEY else "energy"

    print(f"[wake] Starting with engine: {engine}")

    try:
        if engine == "porcupine":
            try:
                run_porcupine()
            except ImportError:
                print("[wake] pvporcupine not installed — falling back to energy detector")
                print("[wake] Install:  pip install pvporcupine")
                run_energy_detector()
        else:
            run_energy_detector()
    except KeyboardInterrupt:
        print("\n[wake] Stopped by user")
        _running = False
    except Exception as e:
        print(f"[wake] Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
