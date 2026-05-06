"""
Javris Global Hotkey Daemon
────────────────────────────
Press Ctrl+Alt+J anywhere on your desktop → Javris listens and responds.

Works on:
  Windows  — pynput (no extra setup)
  Linux X11 — pynput
  Linux Wayland — evdev (see note below)

Run: python ui/hotkey_daemon.py
Deps: pip install pynput httpx
"""

from __future__ import annotations

import platform
import subprocess
import sys
import threading
import time

import httpx

JAVRIS_API  = "http://localhost:8000"
SPEAK_URL   = f"{JAVRIS_API}/api/voice/speak"
COMMAND_URL = f"{JAVRIS_API}/api/voice/command"

# ── Platform-specific notification helper ─────────────────────────

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
            # Use Windows toast via PowerShell (no extra deps)
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$n = New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon = [System.Drawing.SystemIcons]::Information;"
                "$n.Visible = $true;"
                f'$n.ShowBalloonTip({duration_ms}, "{title}", "{body}", [System.Windows.Forms.ToolTipIcon]::Info);'
                "Start-Sleep -Milliseconds 500;"
                "$n.Dispose();"
            )
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
    except Exception:
        print(f"[NOTIFY] {title}: {body}")


# ── Voice trigger ─────────────────────────────────────────────────

_busy = False

def trigger_voice_listen():
    """Ask the backend to do one listen→respond cycle."""
    global _busy
    if _busy:
        return
    _busy = True
    try:
        notify("Javris", "Listening…")
        resp = httpx.post(f"{JAVRIS_API}/api/voice/listen_once", timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            text  = data.get("transcript", "")
            reply = data.get("reply", "")
            if text:
                notify("Javris", f"You: {text}\n{reply[:120]}", 6000)
        elif resp.status_code == 503:
            # Voice not initialised — fall back to showing the web UI
            import webbrowser
            webbrowser.open(JAVRIS_API)
    except httpx.ConnectError:
        notify("Javris", "Server not running — start with: python main.py serve")
    except Exception as e:
        print(f"[hotkey] Error: {e}")
    finally:
        _busy = False


def trigger_quick_command(command: str):
    """Send a text command to the voice command endpoint."""
    try:
        r = httpx.post(COMMAND_URL, json={"text": command, "context": ""}, timeout=15)
        if r.status_code == 200:
            reply = r.json().get("response", "")
            if reply:
                notify("Javris", reply[:160], 5000)
    except Exception as e:
        print(f"[hotkey] Command error: {e}")


# ── pynput listener ───────────────────────────────────────────────

def _start_pynput():
    from pynput import keyboard

    # Ctrl+Alt+J → voice listen
    # Ctrl+Alt+N → news briefing
    # Ctrl+Alt+S → system status
    COMBOS = {
        frozenset([keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char('j')]): trigger_voice_listen,
        frozenset([keyboard.Key.ctrl_r, keyboard.Key.alt_r, keyboard.KeyCode.from_char('j')]): trigger_voice_listen,
        frozenset([keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char('n')]): lambda: threading.Thread(target=trigger_quick_command, args=("latest news",), daemon=True).start(),
        frozenset([keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char('s')]): lambda: threading.Thread(target=trigger_quick_command, args=("system status",), daemon=True).start(),
        frozenset([keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char('w')]): lambda: threading.Thread(target=trigger_quick_command, args=("switch to work mode",), daemon=True).start(),
        frozenset([keyboard.Key.ctrl_l, keyboard.Key.alt_l, keyboard.KeyCode.from_char('t')]): lambda: threading.Thread(target=trigger_quick_command, args=("switch to trading mode",), daemon=True).start(),
    }

    _held = set()

    def on_press(key):
        _held.add(key)
        for combo, fn in COMBOS.items():
            if combo.issubset(_held):
                threading.Thread(target=fn, daemon=True).start()
                return

    def on_release(key):
        _held.discard(key)

    print("[Javris Hotkeys] Active hotkeys:")
    print("  Ctrl+Alt+J  — voice listen")
    print("  Ctrl+Alt+N  — latest news")
    print("  Ctrl+Alt+S  — system status")
    print("  Ctrl+Alt+W  — work mode")
    print("  Ctrl+Alt+T  — trading mode")
    print("Press Ctrl+C to stop.\n")

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


# ── Entry point ───────────────────────────────────────────────────

def main():
    try:
        _start_pynput()
    except ImportError:
        print("[hotkey] pynput not installed. Run: pip install pynput")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[hotkey] Stopped.")


if __name__ == "__main__":
    main()
