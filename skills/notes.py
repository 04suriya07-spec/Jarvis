"""
Notes skill – create, read, search personal notes.
Backed permanently by SQLite.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import aiosqlite

from skills.base import BaseSkill
from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.skill.notes")
cfg = get_config()

DB_PATH = cfg.base_dir / cfg.local_db_path


class NotesSkill(BaseSkill):
    name = "notes"
    description = "Create, read, and search personal notes permanently"

    tool_definition = {
        "name": "notes",
        "description": "Manage personal notes permanently backed in database: create, read, update, delete, search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "read", "update", "delete", "search", "list"],
                },
                "title": {"type": "string", "description": "Note title"},
                "content": {"type": "string", "description": "Note content"},
                "note_id": {"type": "string", "description": "Note ID (for read/update/delete)"},
                "query": {"type": "string", "description": "Search query (for search action)"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags to attach to the note",
                },
            },
            "required": ["action"],
        },
    }

    def __init__(self):
        self._db: aiosqlite.Connection | None = None

    async def _ensure_db(self) -> None:
        if self._db:
            return
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(DB_PATH)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                note_id TEXT PRIMARY KEY,
                title TEXT,
                content TEXT,
                tags TEXT DEFAULT '[]',
                created_at REAL,
                updated_at REAL
            )
        """)
        await self._db.commit()

    async def run(self, action: str, **kwargs) -> Any:
        await self._ensure_db()
        actions = {
            "create": self._create,
            "read": self._read,
            "update": self._update,
            "delete": self._delete,
            "search": self._search,
            "list": self._list,
        }
        fn = actions.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}"}
        return await fn(**kwargs)

    async def _create(self, title: str = "", content: str = "", tags: list = None, **_) -> dict:
        nid = str(uuid.uuid4())[:8]
        now = time.time()
        d = {
            "note_id": nid,
            "title": title,
            "content": content,
            "tags": json.dumps(tags or []),
            "created_at": now,
            "updated_at": now,
        }
        await self._db.execute(
            "INSERT INTO notes VALUES (:note_id,:title,:content,:tags,:created_at,:updated_at)",
            d,
        )
        await self._db.commit()
        return {"success": True, "note_id": nid, "title": title}

    async def _read(self, note_id: str = "", **_) -> dict:
        async with self._db.execute("SELECT * FROM notes WHERE note_id=?", (note_id,)) as cur:
            row = await cur.fetchone()
        if not row:
            return {"error": f"Note {note_id!r} not found"}
        d = dict(row)
        d["tags"] = json.loads(d.get("tags", "[]"))
        return d

    async def _update(self, note_id: str = "", title: str = "", content: str = "", **_) -> dict:
        async with self._db.execute("SELECT * FROM notes WHERE note_id=?", (note_id,)) as cur:
            if not await cur.fetchone():
                return {"error": f"Note {note_id!r} not found"}
        
        sets, params = [], []
        if title:
            sets.append("title=?")
            params.append(title)
        if content:
            sets.append("content=?")
            params.append(content)
        if not sets:
            return {"error": "Nothing to update"}
            
        sets.append("updated_at=?")
        params.append(time.time())
        params.append(note_id)
        
        await self._db.execute(f"UPDATE notes SET {','.join(sets)} WHERE note_id=?", params)
        await self._db.commit()
        return {"success": True, "note_id": note_id}

    async def _delete(self, note_id: str = "", **_) -> dict:
        await self._db.execute("DELETE FROM notes WHERE note_id=?", (note_id,))
        await self._db.commit()
        return {"success": True}

    async def _search(self, query: str = "", **_) -> list[dict]:
        pattern = f"%{query}%"
        async with self._db.execute(
            "SELECT * FROM notes WHERE title LIKE ? OR content LIKE ? OR tags LIKE ? ORDER BY updated_at DESC",
            (pattern, pattern, pattern),
        ) as cur:
            rows = await cur.fetchall()
        
        results = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d.get("tags", "[]"))
            results.append(d)
        return results

    async def _list(self, **_) -> list[dict]:
        async with self._db.execute("SELECT * FROM notes ORDER BY updated_at DESC") as cur:
            rows = await cur.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d.get("tags", "[]"))
            results.append(d)
        return results
