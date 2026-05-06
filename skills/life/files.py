"""
Life Integration — File System
────────────────────────────────
Javris can watch, read, search, and summarise files.
Monitors a configurable set of directories for changes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.files")


class FileSkill(BaseSkill):
    name = "files"
    description = "Read, search, summarise, and monitor files and folders"

    tool_definition = {
        "name": "files",
        "description": (
            "Interact with the local file system. "
            "Actions: read, search, list, summarise, watch_changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["read", "search", "list", "recent_changes"],
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (for search action)",
                },
                "extension": {
                    "type": "string",
                    "description": "Filter by extension, e.g. '.py' or '.txt'",
                },
                "hours": {
                    "type": "integer",
                    "description": "For recent_changes: how many hours back",
                    "default": 24,
                },
            },
            "required": ["action"],
        },
    }

    async def run(self, action: str, **kwargs) -> Any:
        handlers = {
            "read": self._read,
            "search": self._search,
            "list": self._list,
            "recent_changes": self._recent_changes,
        }
        fn = handlers.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}"}
        return await fn(**kwargs)

    async def _read(self, path: str = "", **_) -> dict:
        loop = asyncio.get_event_loop()

        def _do():
            p = Path(path).expanduser()
            if not p.exists():
                return {"error": f"Path not found: {path}"}
            if p.is_dir():
                return {"error": "Path is a directory. Use 'list' action."}
            if p.stat().st_size > 500_000:
                return {"error": "File too large (>500KB). Use search instead."}
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
                return {
                    "path": str(p),
                    "size_bytes": p.stat().st_size,
                    "modified": time.ctime(p.stat().st_mtime),
                    "content": content[:10000],  # first 10k chars
                    "truncated": len(content) > 10000,
                }
            except Exception as e:
                return {"error": str(e)}

        return await loop.run_in_executor(None, _do)

    async def _search(self, path: str = ".", query: str = "", extension: str = "", **_) -> list[dict]:
        loop = asyncio.get_event_loop()

        def _do():
            results = []
            root = Path(path).expanduser()
            if not root.exists():
                return [{"error": f"Path not found: {path}"}]

            pattern = f"**/*{extension}" if extension else "**/*"
            lower_query = query.lower()

            for p in list(root.glob(pattern))[:500]:
                if not p.is_file():
                    continue
                try:
                    if p.stat().st_size > 200_000:
                        continue
                    content = p.read_text(encoding="utf-8", errors="replace")
                    if lower_query in content.lower() or lower_query in p.name.lower():
                        # Find the matching line
                        lines = content.splitlines()
                        matches = [
                            (i + 1, l.strip())
                            for i, l in enumerate(lines)
                            if lower_query in l.lower()
                        ][:3]
                        results.append({
                            "file": str(p),
                            "name": p.name,
                            "matches": matches,
                            "modified": time.ctime(p.stat().st_mtime),
                        })
                        if len(results) >= 20:
                            break
                except Exception:
                    continue
            return results

        return await loop.run_in_executor(None, _do)

    async def _list(self, path: str = ".", extension: str = "", **_) -> list[dict]:
        loop = asyncio.get_event_loop()

        def _do():
            root = Path(path).expanduser()
            if not root.exists():
                return [{"error": f"Path not found: {path}"}]

            entries = []
            try:
                for item in sorted(root.iterdir()):
                    if extension and item.is_file() and item.suffix != extension:
                        continue
                    entries.append({
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size_bytes": item.stat().st_size if item.is_file() else 0,
                        "modified": time.ctime(item.stat().st_mtime),
                    })
            except PermissionError:
                return [{"error": "Permission denied"}]
            return entries[:100]

        return await loop.run_in_executor(None, _do)

    async def _recent_changes(self, path: str = ".", hours: int = 24, extension: str = "", **_) -> list[dict]:
        loop = asyncio.get_event_loop()

        def _do():
            cutoff = time.time() - hours * 3600
            root = Path(path).expanduser()
            pattern = f"**/*{extension}" if extension else "**/*"
            changed = []
            try:
                for p in root.glob(pattern):
                    if p.is_file() and p.stat().st_mtime > cutoff:
                        changed.append({
                            "file": str(p),
                            "name": p.name,
                            "modified": time.ctime(p.stat().st_mtime),
                            "size_bytes": p.stat().st_size,
                        })
            except Exception:
                pass
            changed.sort(key=lambda x: x["modified"], reverse=True)
            return changed[:30]

        return await loop.run_in_executor(None, _do)
