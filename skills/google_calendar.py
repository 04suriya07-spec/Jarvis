"""
Google Calendar skill — thin wrapper that delegates to the real CalendarSkill.
The stub implementation has been removed; full OAuth2 calendar access lives in
skills/life/calendar_skill.py and is registered as 'calendar'.
"""

from __future__ import annotations

from core.models import SkillResult
from skills.base import BaseSkill


class GoogleCalendarSkill(BaseSkill):
    name = "google_calendar"
    description = "Manage Google Calendar events — alias for the 'calendar' skill."

    tool_definition = {
        "name": "google_calendar",
        "description": "List or create Google Calendar events. Actions: list_upcoming, create_event, search_events.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_upcoming", "create_event", "search_events"],
                    "description": "Calendar operation",
                },
                "days": {"type": "integer", "description": "Number of days ahead to look (list_upcoming)"},
                "query": {"type": "string", "description": "Search term (search_events)"},
                "title": {"type": "string", "description": "Event title (create_event)"},
                "start": {"type": "string", "description": "ISO 8601 start datetime (create_event)"},
                "end": {"type": "string", "description": "ISO 8601 end datetime (create_event)"},
            },
            "required": ["action"],
        },
    }

    async def run(self, action: str = "list_upcoming", **kwargs) -> SkillResult:
        # Delegate to the real CalendarSkill
        try:
            from skills.life.calendar_skill import CalendarSkill
            skill = CalendarSkill()
            result = await skill.run(action=action, **kwargs)
            return SkillResult.from_raw(result)
        except Exception as e:
            return SkillResult.fail(
                f"Google Calendar unavailable: {e}. "
                "Complete OAuth at /auth/google or set GMAIL_ADDRESS + GMAIL_APP_PASSWORD in .env"
            )
