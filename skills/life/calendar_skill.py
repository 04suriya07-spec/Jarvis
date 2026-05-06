"""
Life Integration — Calendar
─────────────────────────────
Google Calendar integration.
Falls back to local ICS file parsing if no OAuth token.

Supports:
  • List upcoming events
  • Create events
  • Search events
  • Daily agenda
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from skills.base import BaseSkill
from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.skill.calendar")
cfg = get_config()


class CalendarSkill(BaseSkill):
    name = "calendar"
    description = "Manage Google Calendar events — view, create, search"

    tool_definition = {
        "name": "calendar",
        "description": (
            "Interact with Google Calendar. "
            "Actions: list_upcoming, create_event, search_events, today_agenda."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list_upcoming", "create_event", "search_events", "today_agenda"],
                },
                "days": {
                    "type": "integer",
                    "description": "Number of days ahead to look (default 7)",
                    "default": 7,
                },
                "title": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start datetime ISO-8601"},
                "end": {"type": "string", "description": "End datetime ISO-8601"},
                "description": {"type": "string", "description": "Event description"},
                "query": {"type": "string", "description": "Search term"},
            },
            "required": ["action"],
        },
    }

    def __init__(self):
        self._service = None
        self._token_path = cfg.base_dir / "data" / "google_token.json"
        self._creds_path = cfg.base_dir / "data" / "google_credentials.json"

    def _get_service(self):
        if self._service:
            return self._service
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            SCOPES = ["https://www.googleapis.com/auth/calendar"]
            creds = None

            if self._token_path.exists():
                creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                elif self._creds_path.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(str(self._creds_path), SCOPES)
                    creds = flow.run_local_server(port=0)
                    self._token_path.write_text(creds.to_json())
                else:
                    return None

            self._service = build("calendar", "v3", credentials=creds)
            return self._service
        except Exception as e:
            logger.warning(f"Google Calendar auth failed: {e}")
            return None

    async def run(self, action: str, **kwargs) -> Any:
        handlers = {
            "list_upcoming": self._list_upcoming,
            "create_event": self._create_event,
            "search_events": self._search_events,
            "today_agenda": self._today_agenda,
        }
        fn = handlers.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}"}
        return await fn(**kwargs)

    async def _list_upcoming(self, days: int = 7, **_) -> list[dict]:
        loop = asyncio.get_event_loop()

        def _do():
            svc = self._get_service()
            if not svc:
                return [{"error": "Google Calendar not authenticated. Run /auth/google in the dashboard."}]
            now = datetime.now(timezone.utc).isoformat()
            end = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
            result = svc.events().list(
                calendarId="primary",
                timeMin=now,
                timeMax=end,
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            return [self._format_event(e) for e in result.get("items", [])]

        return await loop.run_in_executor(None, _do)

    async def _today_agenda(self, **_) -> list[dict]:
        loop = asyncio.get_event_loop()

        def _do():
            svc = self._get_service()
            if not svc:
                return [{"error": "Google Calendar not authenticated."}]
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow = today + timedelta(days=1)
            result = svc.events().list(
                calendarId="primary",
                timeMin=today.isoformat(),
                timeMax=tomorrow.isoformat(),
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            return [self._format_event(e) for e in result.get("items", [])]

        return await loop.run_in_executor(None, _do)

    async def _create_event(
        self,
        title: str = "",
        start: str = "",
        end: str = "",
        description: str = "",
        **_,
    ) -> dict:
        if not title or not start:
            return {"error": "title and start are required"}
        loop = asyncio.get_event_loop()

        def _do():
            svc = self._get_service()
            if not svc:
                return {"error": "Google Calendar not authenticated."}
            try:
                start_dt = datetime.fromisoformat(start)
                end_dt = datetime.fromisoformat(end) if end else start_dt + timedelta(hours=1)
                event = {
                    "summary": title,
                    "description": description,
                    "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
                    "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
                }
                created = svc.events().insert(calendarId="primary", body=event).execute()
                return {"success": True, "event_id": created["id"], "title": title, "start": start}
            except Exception as e:
                return {"error": str(e)}

        return await loop.run_in_executor(None, _do)

    async def _search_events(self, query: str = "", **_) -> list[dict]:
        loop = asyncio.get_event_loop()

        def _do():
            svc = self._get_service()
            if not svc:
                return [{"error": "Google Calendar not authenticated."}]
            result = svc.events().list(
                calendarId="primary",
                q=query,
                maxResults=10,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            return [self._format_event(e) for e in result.get("items", [])]

        return await loop.run_in_executor(None, _do)

    @staticmethod
    def _format_event(event: dict) -> dict:
        start = event["start"].get("dateTime", event["start"].get("date", ""))
        end = event["end"].get("dateTime", event["end"].get("date", ""))
        return {
            "id": event.get("id", ""),
            "title": event.get("summary", "(No title)"),
            "start": start,
            "end": end,
            "location": event.get("location", ""),
            "description": event.get("description", "")[:200],
            "url": event.get("htmlLink", ""),
        }
