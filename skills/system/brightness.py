"""
Brightness Skill — brightnessctl / xrandr (Ubuntu/Linux).

Voice commands:
    "set brightness to 70"          → set screen brightness
    "brightness up / brightness down"
    "what's the brightness"
    "turn off screen"               → dpms off (display power saving)
    "turn on screen"                → dpms on
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.brightness")


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


class BrightnessSkill(BaseSkill):
    name = "brightness"
    description = "Control screen brightness and display power on Ubuntu"

    tool_definition = {
        "name": "brightness",
        "description": (
            "Control screen brightness on Ubuntu/Linux. "
            "Actions: get, set, up, down, screen_off, screen_on."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "up", "down", "screen_off", "screen_on"],
                },
                "level": {
                    "type": "integer",
                    "description": "Brightness level 0-100",
                    "minimum": 0,
                    "maximum": 100,
                },
                "step": {
                    "type": "integer",
                    "description": "Step size for up/down (default 10)",
                    "default": 10,
                },
            },
            "required": ["action"],
        },
    }

    async def run(self, action: str, level: int = 70, step: int = 10) -> Any:
        if action == "get":
            return await self._get()
        elif action == "set":
            return await self._set(level)
        elif action == "up":
            return await self._adjust(step)
        elif action == "down":
            return await self._adjust(-step)
        elif action == "screen_off":
            return await self._screen_off()
        elif action == "screen_on":
            return await self._screen_on()
        return {"error": f"Unknown action: {action}"}

    async def _get(self) -> dict:
        # Try brightnessctl first
        rc, out, _ = await _run("brightnessctl get 2>/dev/null")
        rc2, max_out, _ = await _run("brightnessctl max 2>/dev/null")
        if rc == 0 and rc2 == 0 and out and max_out:
            try:
                pct = round(int(out) / int(max_out) * 100)
                return {"brightness": pct, "raw": int(out), "max": int(max_out), "method": "brightnessctl"}
            except ValueError:
                pass

        # Fallback: xrandr
        rc3, out3, _ = await _run(
            "xrandr --verbose 2>/dev/null | grep -i brightness | head -1 | awk '{print $2}'"
        )
        if rc3 == 0 and out3:
            try:
                pct = round(float(out3) * 100)
                return {"brightness": pct, "method": "xrandr"}
            except ValueError:
                pass

        return {"error": "Cannot read brightness. Install: sudo apt install brightnessctl"}

    async def _set(self, level: int) -> dict:
        level = max(0, min(100, level))

        # Try brightnessctl
        rc, _, err = await _run(f"brightnessctl set {level}% 2>/dev/null")
        if rc == 0:
            return {"success": True, "brightness": level, "method": "brightnessctl"}

        # Fallback: xrandr (software brightness, works on all displays)
        ratio = level / 100
        rc2, out2, _ = await _run(
            "xrandr --query 2>/dev/null | grep ' connected' | cut -d' ' -f1 | head -1"
        )
        monitor = out2.strip() if rc2 == 0 else "eDP-1"
        rc3, _, err3 = await _run(f"xrandr --output {monitor} --brightness {ratio:.2f} 2>/dev/null")
        if rc3 == 0:
            return {"success": True, "brightness": level, "method": "xrandr", "monitor": monitor}

        return {"error": f"Cannot set brightness: {err or err3}. Try: sudo apt install brightnessctl"}

    async def _adjust(self, delta: int) -> dict:
        result = await self._get()
        if "error" in result:
            return result
        current = result["brightness"]
        return await self._set(current + delta)

    async def _screen_off(self) -> dict:
        rc, _, err = await _run("xset dpms force off 2>/dev/null")
        return {"success": rc == 0, "message": "Screen turned off" if rc == 0 else err}

    async def _screen_on(self) -> dict:
        rc, _, err = await _run("xset dpms force on && xset s off 2>/dev/null")
        return {"success": rc == 0, "message": "Screen turned on" if rc == 0 else err}
