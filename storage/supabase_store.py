"""
Javris Supabase Storage
────────────────────────
Stores structured data in Supabase (PostgreSQL + REST API):

  Tables (auto-created on first use):
    chat_history      — full conversation log with session IDs
    user_preferences  — key-value settings store
    ai_memory         — facts and patterns from IntelligenceEngine
    file_metadata     — file records from LocalStore + Degoo sync status

Design:
  • Uses supabase-py client (async-compatible via thread executor)
  • All writes are fire-and-forget (sync_chat, sync_memory, etc.)
  • Each record has a `synced` flag — local-first, cloud-backup
  • Falls back silently if Supabase is unconfigured or unreachable
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.storage.supabase")
cfg = get_config()


class SupabaseStore:
    """
    Async-friendly Supabase client wrapper.

    All operations return gracefully on error — Supabase is optional.
    The local SQLite DB is always the source of truth.
    """

    def __init__(self):
        self._client = None
        self._available = False

    def init(self) -> None:
        """Initialise Supabase client. Safe to call even without credentials."""
        if not cfg.supabase_url or not cfg.supabase_anon_key:
            logger.info("Supabase not configured — cloud sync disabled")
            return

        try:
            from supabase import create_client
            self._client = create_client(cfg.supabase_url, cfg.supabase_anon_key)
            self._available = True
            logger.info(f"Supabase connected: {cfg.supabase_url}")
        except Exception as e:
            logger.warning(f"Supabase init failed: {e}")

    @property
    def available(self) -> bool:
        return self._available and self._client is not None

    # ── Internal helpers ──────────────────────────────────────

    async def _run(self, fn) -> Optional[Any]:
        """Run a synchronous Supabase call in a thread executor."""
        if not self.available:
            return None
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, fn)
        except Exception as e:
            logger.debug(f"Supabase error: {e}")
            return None

    def _upsert(self, table: str, data: dict, on_conflict: str = "id"):
        """Upsert a single row (sync, run via _run)."""
        return self._client.table(table).upsert(data, on_conflict=on_conflict).execute()

    def _insert(self, table: str, data: dict):
        return self._client.table(table).insert(data).execute()

    def _select(self, table: str, filters: dict = None, limit: int = 50):
        q = self._client.table(table).select("*")
        if filters:
            for col, val in filters.items():
                q = q.eq(col, val)
        return q.limit(limit).execute()

    # ── Chat history ──────────────────────────────────────────

    async def sync_message(self, message: dict) -> None:
        """
        Push a single chat message to Supabase chat_history.
        message: {message_id, session_id, role, content, timestamp, metadata}
        """
        row = {
            "id":         message.get("message_id", ""),
            "session_id": message.get("session_id", ""),
            "role":       message.get("role", "user"),
            "content":    message.get("content", ""),
            "timestamp":  message.get("timestamp", time.time()),
            "metadata":   json.dumps(message.get("metadata", {})),
        }
        await self._run(lambda: self._upsert("chat_history", row, on_conflict="id"))

    async def sync_session(self, session_id: str, messages: list[dict]) -> None:
        """Push all messages in a session to Supabase."""
        for msg in messages:
            msg["session_id"] = session_id
            await self.sync_message(msg)

    async def get_chat_history(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve chat history from Supabase."""
        filters = {"session_id": session_id} if session_id else {}

        def _fetch():
            q = self._client.table("chat_history").select("*")
            if session_id:
                q = q.eq("session_id", session_id)
            return q.order("timestamp", desc=False).limit(limit).execute()

        result = await self._run(_fetch)
        if result and hasattr(result, "data"):
            return result.data or []
        return []

    # ── User preferences ──────────────────────────────────────

    async def set_preference(self, key: str, value: Any) -> None:
        """Store a user preference key-value pair."""
        row = {
            "id":         key,
            "value":      json.dumps(value),
            "updated_at": time.time(),
        }
        await self._run(lambda: self._upsert("user_preferences", row, on_conflict="id"))

    async def get_preference(self, key: str, default: Any = None) -> Any:
        """Retrieve a preference by key."""
        def _fetch():
            return self._client.table("user_preferences").select("value").eq("id", key).execute()

        result = await self._run(_fetch)
        if result and result.data:
            try:
                return json.loads(result.data[0]["value"])
            except Exception:
                pass
        return default

    async def get_all_preferences(self) -> dict:
        """Return all stored preferences as a dict."""
        def _fetch():
            return self._client.table("user_preferences").select("id,value").execute()

        result = await self._run(_fetch)
        if result and result.data:
            out = {}
            for row in result.data:
                try:
                    out[row["id"]] = json.loads(row["value"])
                except Exception:
                    out[row["id"]] = row["value"]
            return out
        return {}

    # ── AI Memory (facts + patterns) ──────────────────────────

    async def sync_memory(self, facts: list[dict], patterns: list[dict]) -> None:
        """Push intelligence engine data to Supabase ai_memory table."""
        for fact in facts:
            row = {
                "id":         fact.get("fact_id", ""),
                "type":       "fact",
                "category":   fact.get("category", "general"),
                "content":    fact.get("statement", ""),
                "confidence": fact.get("confidence", 0.7),
                "metadata":   json.dumps({k: v for k, v in fact.items()
                                          if k not in ("fact_id", "category", "statement", "confidence")}),
                "updated_at": time.time(),
            }
            await self._run(lambda r=row: self._upsert("ai_memory", r, on_conflict="id"))

        for pattern in patterns:
            row = {
                "id":         pattern.get("pattern_id", ""),
                "type":       "pattern",
                "category":   pattern.get("time_of_day", "general"),
                "content":    pattern.get("description", ""),
                "confidence": pattern.get("confidence", 0.5),
                "metadata":   json.dumps({k: v for k, v in pattern.items()
                                          if k not in ("pattern_id", "description", "confidence")}),
                "updated_at": time.time(),
            }
            await self._run(lambda r=row: self._upsert("ai_memory", r, on_conflict="id"))

    async def get_memory(self, memory_type: str = "fact") -> list[dict]:
        """Retrieve stored AI memory records."""
        def _fetch():
            return (
                self._client.table("ai_memory")
                .select("*")
                .eq("type", memory_type)
                .order("confidence", desc=True)
                .limit(100)
                .execute()
            )
        result = await self._run(_fetch)
        return result.data if result and result.data else []

    # ── File metadata ─────────────────────────────────────────

    async def sync_file(self, record: dict) -> None:
        """Push a FileRecord dict to Supabase file_metadata."""
        row = {
            "id":          record.get("file_id", ""),
            "filename":    record.get("filename", ""),
            "category":    record.get("category", "temp"),
            "path":        record.get("path", ""),
            "size_bytes":  record.get("size_bytes", 0),
            "mime_type":   record.get("mime_type", ""),
            "tags":        json.dumps(record.get("tags", [])),
            "synced":      True,
            "cold":        record.get("cold", False),
            "created_at":  record.get("created_at", time.time()),
        }
        await self._run(lambda: self._upsert("file_metadata", row, on_conflict="id"))

    async def get_files(
        self,
        category: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query file metadata from Supabase."""
        def _fetch():
            q = self._client.table("file_metadata").select("*")
            if category:
                q = q.eq("category", category)
            return q.order("created_at", desc=True).limit(limit).execute()

        result = await self._run(_fetch)
        return result.data if result and result.data else []

    async def mark_cold(self, file_id: str) -> None:
        """Mark a file as moved to Degoo cold storage."""
        await self._run(
            lambda: self._client.table("file_metadata")
            .update({"cold": True})
            .eq("id", file_id)
            .execute()
        )

    # ── Schema bootstrap ──────────────────────────────────────

    async def ensure_tables(self) -> None:
        """
        Log instructions for creating required tables.
        Supabase doesn't support CREATE TABLE via REST — run SQL in the dashboard.
        """
        if not self.available:
            return

        sql = """
-- Run this SQL in your Supabase dashboard → SQL Editor

CREATE TABLE IF NOT EXISTS chat_history (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    timestamp   DOUBLE PRECISION,
    metadata    TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_history (session_id);

CREATE TABLE IF NOT EXISTS user_preferences (
    id         TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS ai_memory (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    category   TEXT,
    content    TEXT,
    confidence REAL,
    metadata   TEXT DEFAULT '{}',
    updated_at DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS file_metadata (
    id         TEXT PRIMARY KEY,
    filename   TEXT,
    category   TEXT,
    path       TEXT,
    size_bytes BIGINT,
    mime_type  TEXT,
    tags       TEXT DEFAULT '[]',
    synced     BOOLEAN DEFAULT FALSE,
    cold       BOOLEAN DEFAULT FALSE,
    created_at DOUBLE PRECISION
);
"""
        logger.info("Supabase table SQL (run in dashboard if tables don't exist):\n" + sql)
