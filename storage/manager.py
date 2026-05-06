"""
Javris Storage Manager
───────────────────────
Unified interface over all three storage tiers:

  Tier 1 — Local   (instant, always available)
  Tier 2 — Supabase (structured, cloud-sync, optional)
  Tier 3 — Degoo   (cold, large files, optional)

Retrieval priority: Local → Supabase metadata → Degoo

Usage::

    storage = StorageManager()
    storage.init()

    # Save a file
    record = storage.save_file(data, "recording.wav", category="audio")

    # Sync a chat message to Supabase
    await storage.sync_message({...})

    # Query past chat history from Supabase
    history = await storage.get_history(session_id="abc123")
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Optional

from core.config import get_config
from core.logger import get_logger
from storage.local_store import LocalStore, FileRecord
from storage.supabase_store import SupabaseStore
from storage.degoo_sync import DegooSyncWatcher

logger = get_logger("javris.storage.manager")
cfg = get_config()


class StorageManager:
    """
    The single storage entry point for all Javris components.
    All cloud operations are async and fire-and-forget.
    """

    def __init__(self):
        self.local    = LocalStore()
        self.supabase = SupabaseStore()
        self._degoo: Optional[DegooSyncWatcher] = None

    def init(self) -> None:
        """Initialise all storage tiers. Call once at startup."""
        self.local.init()
        self.supabase.init()

        if cfg.supabase_url:
            self._degoo = DegooSyncWatcher(self.supabase)
            if cfg.storage_auto_sync:
                self._degoo.start()

        logger.info(
            f"StorageManager ready | "
            f"supabase={'on' if self.supabase.available else 'off'} | "
            f"degoo={'on' if self._degoo else 'off'}"
        )

    # ── File operations ───────────────────────────────────────

    def save_file(
        self,
        data: bytes,
        filename: str,
        category: str = "temp",
        tags: list | None = None,
        mime_type: str = "",
    ) -> FileRecord:
        """
        Save a file to local storage.
        Automatically queues cold-storage if file exceeds threshold.
        """
        record = self.local.save(data, filename, category, tags, mime_type)

        # Async: push metadata to Supabase
        asyncio.create_task(self.supabase.sync_file(record.to_dict()))

        # Move large files to Degoo sync folder
        if self.local.should_cold_store(record):
            record = self.local.move_to_cold(record)
            asyncio.create_task(self.supabase.mark_cold(record.file_id))

        return record

    def save_file_from_path(self, src: Path, category: str = "temp") -> FileRecord:
        """Save a file from an existing path."""
        return self.save_file(src.read_bytes(), src.name, category)

    def read_file(self, category: str, filename: str) -> Optional[bytes]:
        """Read local file. Returns None if not found."""
        return self.local.get(category, filename)

    def get_file_path(self, category: str, filename: str) -> Optional[Path]:
        """Return absolute path if file exists locally."""
        return self.local.get_path(category, filename)

    # ── Chat history ──────────────────────────────────────────

    async def sync_message(self, message: dict) -> None:
        """Push a chat message to Supabase (fire-and-forget safe)."""
        if cfg.storage_auto_sync:
            await self.supabase.sync_message(message)

    async def sync_session(self, session_id: str, messages: list[dict]) -> None:
        """Sync all messages in a session to Supabase."""
        if cfg.storage_auto_sync:
            await self.supabase.sync_session(session_id, messages)

    async def get_history(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Retrieve chat history.
        Returns Supabase records if available, else empty list.
        """
        return await self.supabase.get_chat_history(session_id, limit)

    # ── Preferences ───────────────────────────────────────────

    async def set_pref(self, key: str, value: Any) -> None:
        await self.supabase.set_preference(key, value)

    async def get_pref(self, key: str, default: Any = None) -> Any:
        return await self.supabase.get_preference(key, default)

    async def get_all_prefs(self) -> dict:
        return await self.supabase.get_all_preferences()

    # ── AI Memory sync ────────────────────────────────────────

    async def sync_intelligence(self, intelligence_engine) -> None:
        """Sync IntelligenceEngine state to Supabase ai_memory."""
        facts    = intelligence_engine.get_all_facts()
        patterns = intelligence_engine.get_all_patterns()
        await self.supabase.sync_memory(facts, patterns)

    # ── File metadata queries ─────────────────────────────────

    async def list_files(self, category: str | None = None) -> list[dict]:
        """List stored file metadata from Supabase."""
        return await self.supabase.get_files(category)

    def disk_usage(self) -> dict:
        return self.local.disk_usage()

    def degoo_pending(self) -> list[dict]:
        return self._degoo.list_pending_sync() if self._degoo else []

    def degoo_instructions(self) -> str:
        if self._degoo:
            return self._degoo.setup_instructions()
        return "Degoo sync not initialised (Supabase required)"

    # ── Cleanup ───────────────────────────────────────────────

    async def cleanup(self, temp_hours: int = 24) -> dict:
        """Housekeeping — remove stale temp files, sync pending records."""
        deleted = self.local.cleanup_temp(temp_hours)
        return {"temp_files_deleted": deleted}

    def close(self) -> None:
        if self._degoo:
            self._degoo.stop()

    # ── Status ────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "supabase": self.supabase.available,
            "degoo_watcher": self._degoo is not None,
            "local_root": str(cfg.jarvis_data_path),
            "degoo_sync_folder": str(cfg.degoo_sync_path),
            "disk_usage": self.disk_usage(),
        }
