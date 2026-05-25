"""
Desktop Notification Skill — notify-send (Ubuntu/Linux).

Voice commands:
    "remind me in 5 minutes to drink water"   → scheduled desktop popup
    "send a notification: meeting now"         → immediate popup
    "set a timer for 10 minutes"               → countdown then notify
"""

from __future__ import annotations

import asyncio
from typing import Any

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.notify")


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


class NotifySkill(BaseSkill):
    name = "notify"
    description = "Send desktop notifications and set timed reminders on Ubuntu"

    tool_definition = {
        "name": "notify",
        "description": (
            "Send desktop popup notifications or set timed reminders. "
            "Actions: send, remind, timer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["send", "remind", "timer"],
                },
                "title": {
                    "type": "string",
                    "description": "Notification title (default: Javris)",
                },
                "message": {
                    "type": "string",
                    "description": "Notification body text",
                },
                "delay_seconds": {
                    "type": "integer",
                    "description": "Seconds before showing reminder/timer notification",
                    "default": 0,
                },
                "urgency": {
                    "type": "string",
                    "enum": ["low", "normal", "critical"],
                    "default": "normal",
                },
            },
            "required": ["action", "message"],
        },
    }

    async def run(self, action: str, message: str = "", title: str = "Javris",
                  delay_seconds: int = 0, urgency: str = "normal") -> Any:
        if action == "send":
            return await self._send(title, message, urgency)
        elif action in ("remind", "timer"):
            return await self._remind(title, message, delay_seconds, urgency)
        return {"error": f"Unknown action: {action}"}

    async def _send(self, title: str, message: str, urgency: str = "normal") -> dict:
        safe_title = title.replace('"', "'")
        safe_msg = message.replace('"', "'")
        rc, _, err = await _run(
            f'notify-send --urgency={urgency} --icon=dialog-information "{safe_title}" "{safe_msg}"'
        )
        if rc == 0:
            return {"success": True, "title": title, "message": message}

        # Fallback: zenity info dialog (no urgency levels but works)
        rc2, _, _ = await _run(f'zenity --info --title="{safe_title}" --text="{safe_msg}" &')
        if rc2 == 0:
            return {"success": True, "method": "zenity"}

        return {"error": "notify-send not found. Run: sudo apt install libnotify-bin"}

    async def _remind(self, title: str, message: str, delay_seconds: int, urgency: str) -> dict:
        if delay_seconds <= 0:
            return await self._send(title, message, urgency)

        async def _delayed():
            await asyncio.sleep(delay_seconds)
            await self._send(title, message, urgency)

        asyncio.create_task(_delayed())

        minutes = delay_seconds // 60
        seconds = delay_seconds % 60
        time_str = f"{minutes}m {seconds}s" if minutes else f"{seconds}s"
        return {
            "success": True,
            "message": f"Reminder set for {time_str}: '{message}'",
            "fires_in_seconds": delay_seconds,
        }
