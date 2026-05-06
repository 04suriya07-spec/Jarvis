"""
Javris Degoo Cold Storage Sync
────────────────────────────────
Degoo doesn't provide a public API, so we use the "watched folder" approach:

  • Files placed in jarvis_data/degoo_sync/ are auto-synced by Degoo's
    desktop client (if installed and logged in)
  • This module watches what goes in/out of that folder via watchdog
  • Marks Supabase file_metadata records as `cold=True` once a file
    appears in the sync folder

No Degoo API key required — just install the Degoo desktop app and
point it to jarvis_data/degoo_sync/.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import TYPE_CHECKING

from core.config import get_config
from core.logger import get_logger

if TYPE_CHECKING:
    from storage.supabase_store import SupabaseStore

logger = get_logger("javris.storage.degoo")
cfg = get_config()


class DegooSyncWatcher:
    """
    Watches the Degoo sync folder and updates Supabase metadata
    when files appear or disappear.
    """

    def __init__(self, supabase: "SupabaseStore"):
        self._supabase = supabase
        self._sync_dir = cfg.degoo_sync_path
        self._observer = None
        self._known_files: set[str] = set()

    def start(self) -> None:
        """Start the watchdog observer in a background thread."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class _Handler(FileSystemEventHandler):
                def __init__(self, watcher: DegooSyncWatcher):
                    self._w = watcher

                def on_created(self, event):
                    if not event.is_directory:
                        asyncio.run_coroutine_threadsafe(
                            self._w._on_file_added(Path(event.src_path)),
                            asyncio.get_event_loop(),
                        )

                def on_deleted(self, event):
                    if not event.is_directory:
                        logger.debug(f"Degoo: removed from sync folder: {event.src_path}")

            self._observer = Observer()
            self._observer.schedule(_Handler(self), str(self._sync_dir), recursive=False)
            self._observer.start()
            logger.info(f"Degoo sync watcher started: {self._sync_dir}")
        except Exception as e:
            logger.warning(f"Degoo watcher failed to start: {e}")

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join()

    async def _on_file_added(self, path: Path) -> None:
        """Called when a new file lands in the sync folder."""
        filename = path.name
        if filename in self._known_files:
            return
        self._known_files.add(filename)

        # Update Supabase: mark as cold (file is now in Degoo)
        file_id = filename.split("_")[0] if "_" in filename else filename[:16]
        await self._supabase.mark_cold(file_id)
        logger.info(f"Degoo: marked cold — {filename}")

    # ── Utilities ─────────────────────────────────────────────

    def list_pending_sync(self) -> list[dict]:
        """Files currently in the Degoo sync folder (awaiting upload)."""
        return [
            {
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "added_at": f.stat().st_mtime,
            }
            for f in self._sync_dir.iterdir()
            if f.is_file()
        ]

    def sync_folder_path(self) -> str:
        return str(self._sync_dir)

    def setup_instructions(self) -> str:
        return (
            f"Degoo Cold Storage Setup:\n"
            f"1. Install Degoo desktop app from degoo.com\n"
            f"2. Log in to your Degoo account\n"
            f"3. Add this folder to Degoo sync: {self._sync_dir}\n"
            f"4. Javris will automatically move large files there\n"
            f"5. Degoo uploads them to cloud in the background"
        )
