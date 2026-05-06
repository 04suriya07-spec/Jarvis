"""Task Scheduler skill – set reminders and recurring tasks."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.scheduler")

# In-memory store; persisted to DB via assistant
_reminders: dict[str, dict] = {}


class SchedulerSkill(BaseSkill):
    name = "scheduler"
    description = "Set reminders and schedule tasks"

    tool_definition = {
        "name": "scheduler",
        "description": "Create, list, or cancel reminders and scheduled tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "cancel"],
                },
                "title": {
                    "type": "string",
                    "description": "What to remind about",
                },
                "when": {
                    "type": "string",
                    "description": (
                        "ISO-8601 datetime or natural time like "
                        "'in 30 minutes', 'tomorrow at 9am', '2025-12-25 10:00'"
                    ),
                },
                "reminder_id": {
                    "type": "string",
                    "description": "ID to cancel (used with action=cancel)",
                },
            },
            "required": ["action"],
        },
    }

    def __init__(self):
        self._scheduler = None
        self._init_scheduler()

    def _init_scheduler(self) -> None:
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            self._scheduler = AsyncIOScheduler()
            self._scheduler.start()
        except Exception as e:
            logger.warning(f"APScheduler init failed: {e}")

    async def run(self, action: str, **kwargs) -> Any:
        if action == "create":
            return await self._create(**kwargs)
        elif action == "list":
            return self._list()
        elif action == "cancel":
            return self._cancel(kwargs.get("reminder_id", ""))
        return {"error": f"Unknown action: {action}"}

    async def _create(
        self, title: str = "", when: str = "", **_
    ) -> dict:
        if not title or not when:
            return {"error": "title and when are required"}

        run_at = self._parse_time(when)
        if not run_at:
            return {"error": f"Could not parse time: {when!r}"}

        rid = str(uuid.uuid4())[:8]
        _reminders[rid] = {
            "id": rid,
            "title": title,
            "when": run_at.isoformat(),
            "status": "pending",
        }

        if self._scheduler:
            self._scheduler.add_job(
                self._fire_reminder,
                "date",
                run_date=run_at,
                args=[rid, title],
                id=rid,
            )

        return {
            "success": True,
            "reminder_id": rid,
            "title": title,
            "scheduled_for": run_at.strftime("%Y-%m-%d %H:%M"),
        }

    def _list(self) -> list[dict]:
        return list(_reminders.values())

    def _cancel(self, reminder_id: str) -> dict:
        if reminder_id not in _reminders:
            return {"error": "Reminder not found"}
        _reminders[reminder_id]["status"] = "cancelled"
        if self._scheduler:
            try:
                self._scheduler.remove_job(reminder_id)
            except Exception:
                pass
        return {"success": True, "cancelled": reminder_id}

    async def _fire_reminder(self, rid: str, title: str) -> None:
        logger.info(f"Reminder fired: {title}")
        if rid in _reminders:
            _reminders[rid]["status"] = "done"
        # TODO: integrate with voice/notification system

    def _parse_time(self, when_str: str) -> datetime | None:
        """Parse natural language or ISO time strings."""
        import arrow

        try:
            return arrow.get(when_str).datetime
        except Exception:
            pass

        # Natural language fallback
        now = arrow.now()
        lower = when_str.lower().strip()
        try:
            if lower.startswith("in "):
                parts = lower[3:].split()
                amount = int(parts[0])
                unit = parts[1].rstrip("s")
                return now.shift(**{unit + "s": amount}).datetime
            elif "tomorrow" in lower:
                time_part = lower.replace("tomorrow", "").replace("at", "").strip()
                if time_part:
                    h, m = (time_part.split(":") + ["0"])[:2]
                    return now.shift(days=1).replace(
                        hour=int(h), minute=int(m), second=0
                    ).datetime
                return now.shift(days=1).datetime
        except Exception:
            pass

        return None
