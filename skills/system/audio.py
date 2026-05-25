"""
Audio / Volume Skill — pactl + playerctl (Ubuntu/Linux).

Voice commands:
    "set volume to 60"             → set master volume
    "volume up / volume down"      → +10% / -10%
    "mute / unmute"                → toggle mute
    "what's the volume"            → report current level
    "play / pause"                 → media control
    "next / previous song"         → skip tracks
    "stop music"                   → stop playback
    "what's playing"               → current track info
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.audio")


async def _run(cmd: str, timeout: int = 10) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode(errors="replace").strip(), stderr.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "Timed out"


class AudioSkill(BaseSkill):
    name = "audio"
    description = "Control system volume and media playback (play/pause/next/volume)"

    tool_definition = {
        "name": "audio",
        "description": (
            "Control audio volume and media playback on Ubuntu. "
            "Actions: get_volume, set_volume, volume_up, volume_down, mute, unmute, "
            "play, pause, next, previous, stop, now_playing, list_sinks, set_sink."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "get_volume", "set_volume", "volume_up", "volume_down",
                        "mute", "unmute", "play", "pause", "next", "previous",
                        "stop", "now_playing", "list_sinks", "set_sink",
                    ],
                },
                "level": {
                    "type": "integer",
                    "description": "Volume level 0-100 (for set_volume)",
                    "minimum": 0,
                    "maximum": 100,
                },
                "step": {
                    "type": "integer",
                    "description": "Step size for volume_up/down (default 10)",
                    "default": 10,
                },
                "sink": {
                    "type": "string",
                    "description": "Audio output device name (for set_sink)",
                },
            },
            "required": ["action"],
        },
    }

    async def run(self, action: str, level: int = 50, step: int = 10, sink: str = "") -> Any:
        handlers = {
            "get_volume": self._get_volume,
            "set_volume": lambda **kw: self._set_volume(level),
            "volume_up": lambda **kw: self._adjust_volume(step),
            "volume_down": lambda **kw: self._adjust_volume(-step),
            "mute": self._mute,
            "unmute": self._unmute,
            "play": lambda **kw: self._playerctl("play"),
            "pause": lambda **kw: self._playerctl("pause"),
            "next": lambda **kw: self._playerctl("next"),
            "previous": lambda **kw: self._playerctl("previous"),
            "stop": lambda **kw: self._playerctl("stop"),
            "now_playing": self._now_playing,
            "list_sinks": self._list_sinks,
            "set_sink": lambda **kw: self._set_sink(sink),
        }
        fn = handlers.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}"}
        return await fn()

    async def _get_volume(self) -> dict:
        rc, out, err = await _run(
            "pactl get-sink-volume @DEFAULT_SINK@ 2>/dev/null | grep -oP '\\d+(?=%)' | head -1"
        )
        if rc == 0 and out:
            vol = int(out.strip())
            rc2, mute_out, _ = await _run("pactl get-sink-mute @DEFAULT_SINK@ 2>/dev/null")
            muted = "yes" in mute_out.lower() if rc2 == 0 else False
            return {"volume": vol, "muted": muted}

        # Fallback: amixer
        rc3, out3, _ = await _run("amixer sget Master 2>/dev/null | grep -oP '\\d+(?=%)' | head -1")
        if rc3 == 0 and out3:
            return {"volume": int(out3.strip()), "muted": False}

        return {"error": "Cannot read volume. Install pulseaudio-utils: sudo apt install pulseaudio-utils"}

    async def _set_volume(self, level: int) -> dict:
        level = max(0, min(100, level))
        rc, _, err = await _run(f"pactl set-sink-volume @DEFAULT_SINK@ {level}%")
        if rc == 0:
            return {"success": True, "volume": level}
        # Fallback amixer
        rc2, _, _ = await _run(f"amixer sset Master {level}%")
        return {"success": rc2 == 0, "volume": level}

    async def _adjust_volume(self, delta: int) -> dict:
        result = await self._get_volume()
        if "error" in result:
            return result
        current = result["volume"]
        new_level = max(0, min(100, current + delta))
        return await self._set_volume(new_level)

    async def _mute(self) -> dict:
        rc, _, err = await _run("pactl set-sink-mute @DEFAULT_SINK@ 1")
        if rc != 0:
            rc, _, err = await _run("amixer sset Master mute")
        return {"success": rc == 0, "muted": True}

    async def _unmute(self) -> dict:
        rc, _, err = await _run("pactl set-sink-mute @DEFAULT_SINK@ 0")
        if rc != 0:
            rc, _, err = await _run("amixer sset Master unmute")
        return {"success": rc == 0, "muted": False}

    async def _playerctl(self, command: str) -> dict:
        rc, out, err = await _run(f"playerctl {command} 2>/dev/null")
        if rc == 0:
            return {"success": True, "action": command}
        # Fallback: xdotool key for media keys
        key_map = {"play": "XF86AudioPlay", "pause": "XF86AudioPause",
                   "next": "XF86AudioNext", "previous": "XF86AudioPrev", "stop": "XF86AudioStop"}
        key = key_map.get(command)
        if key:
            rc2, _, _ = await _run(f"xdotool key {key} 2>/dev/null")
            return {"success": rc2 == 0, "action": command, "method": "xdotool"}
        return {"success": False, "error": err or "playerctl not installed. Run: sudo apt install playerctl"}

    async def _now_playing(self) -> dict:
        rc, title, _ = await _run("playerctl metadata title 2>/dev/null")
        rc2, artist, _ = await _run("playerctl metadata artist 2>/dev/null")
        rc3, status, _ = await _run("playerctl status 2>/dev/null")
        rc4, album, _ = await _run("playerctl metadata album 2>/dev/null")

        if rc != 0:
            return {"error": "No active media player found (playerctl). Playing anything?"}

        return {
            "title": title,
            "artist": artist,
            "album": album,
            "status": status.lower(),
        }

    async def _list_sinks(self) -> list[dict]:
        rc, out, _ = await _run("pactl list short sinks 2>/dev/null")
        if rc != 0:
            return [{"error": "pactl not available"}]
        sinks = []
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                sinks.append({"index": parts[0], "name": parts[1]})
        return sinks

    async def _set_sink(self, sink: str) -> dict:
        if not sink:
            return {"error": "Sink name required"}
        rc, _, err = await _run(f'pactl set-default-sink "{sink}"')
        return {"success": rc == 0, "sink": sink, "error": err if rc != 0 else None}
