"""
Javris Local Storage
─────────────────────
Manages the local jarvis_data/ folder structure:

  jarvis_data/
    audio/          voice recordings, TTS cache
    images/         screenshots, vision captures
    logs/           archived logs
    temp/           ephemeral processing files
    degoo_sync/     cold-storage folder (Degoo desktop watches this)

Each file is tracked with a metadata record (stored in Supabase).
"""

from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.storage.local")
cfg = get_config()


@dataclass
class FileRecord:
    """Metadata for a stored file."""
    file_id: str            # SHA-256 (first 16 chars)
    filename: str
    category: str           # audio | images | logs | temp
    path: str               # relative to jarvis_data/
    size_bytes: int
    created_at: float
    mime_type: str = ""
    tags: list = None
    synced: bool = False    # True once written to Supabase
    cold: bool = False      # True once moved to Degoo sync folder

    def __post_init__(self):
        if self.tags is None:
            self.tags = []

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tags"] = self.tags
        return d


class LocalStore:
    """
    Local file store with folder structure management.

    Folders are created lazily — call init() once at startup.
    """

    CATEGORIES = ["audio", "images", "logs", "temp"]

    def __init__(self):
        self._root = cfg.jarvis_data_path
        self._degoo = cfg.degoo_sync_path
        self._dirs: dict[str, Path] = {}

    def init(self) -> None:
        """Create all sub-directories if they don't exist."""
        for cat in self.CATEGORIES:
            d = self._root / cat
            d.mkdir(parents=True, exist_ok=True)
            self._dirs[cat] = d
        logger.info(f"LocalStore ready at {self._root}")

    # ── Write ─────────────────────────────────────────────────

    def save(
        self,
        data: bytes,
        filename: str,
        category: str = "temp",
        tags: list | None = None,
        mime_type: str = "",
    ) -> FileRecord:
        """
        Save bytes to local storage. Returns FileRecord.
        Automatically creates category directory.
        """
        if category not in self.CATEGORIES:
            category = "temp"

        dest_dir = self._dirs.get(category) or (self._root / category)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename

        dest.write_bytes(data)

        file_id = hashlib.sha256(data).hexdigest()[:16]
        record = FileRecord(
            file_id=file_id,
            filename=filename,
            category=category,
            path=str(dest.relative_to(self._root)),
            size_bytes=len(data),
            created_at=time.time(),
            mime_type=mime_type,
            tags=tags or [],
        )
        logger.debug(f"Saved {category}/{filename} ({len(data)} bytes)")
        return record

    def save_path(
        self,
        src: Path,
        category: str = "temp",
        tags: list | None = None,
    ) -> FileRecord:
        """Copy an existing file into local storage."""
        data = src.read_bytes()
        return self.save(data, src.name, category, tags)

    # ── Read ──────────────────────────────────────────────────

    def get(self, category: str, filename: str) -> Optional[bytes]:
        """Read a file. Returns None if not found."""
        path = (self._dirs.get(category) or self._root / category) / filename
        if path.exists():
            return path.read_bytes()
        return None

    def get_path(self, category: str, filename: str) -> Optional[Path]:
        """Return the absolute path if the file exists."""
        path = (self._dirs.get(category) or self._root / category) / filename
        return path if path.exists() else None

    # ── Cold storage (Degoo) ──────────────────────────────────

    def move_to_cold(self, record: FileRecord) -> FileRecord:
        """
        Move a file to the Degoo auto-sync folder.
        Degoo's desktop client picks it up automatically.
        Large files (> threshold) should be cold-stored.
        """
        src = self._root / record.path
        if not src.exists():
            logger.warning(f"Cold move: source not found {src}")
            return record

        dest = self._degoo / record.filename
        shutil.move(str(src), str(dest))
        record.cold = True
        record.path = str(dest.relative_to(self._root.parent))
        logger.info(f"Moved to cold storage: {record.filename}")
        return record

    def should_cold_store(self, record: FileRecord) -> bool:
        """True if the file exceeds the cold-storage size threshold."""
        threshold = cfg.storage_cold_threshold_mb * 1024 * 1024
        return record.size_bytes > threshold

    # ── Cleanup ───────────────────────────────────────────────

    def cleanup_temp(self, older_than_hours: int = 24) -> int:
        """Delete temp files older than given hours. Returns count deleted."""
        cutoff = time.time() - older_than_hours * 3600
        deleted = 0
        temp_dir = self._dirs.get("temp", self._root / "temp")
        for f in temp_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        if deleted:
            logger.info(f"Cleaned {deleted} temp files")
        return deleted

    # ── List ──────────────────────────────────────────────────

    def list_category(self, category: str) -> list[dict]:
        """List files in a category."""
        d = self._dirs.get(category, self._root / category)
        if not d.exists():
            return []
        return [
            {
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "modified": f.stat().st_mtime,
            }
            for f in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
            if f.is_file()
        ]

    def disk_usage(self) -> dict:
        """Return disk usage stats per category."""
        stats = {}
        for cat in self.CATEGORIES:
            d = self._dirs.get(cat, self._root / cat)
            if d.exists():
                total = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                stats[cat] = {"files": sum(1 for f in d.iterdir() if f.is_file()), "bytes": total}
            else:
                stats[cat] = {"files": 0, "bytes": 0}
        return stats
