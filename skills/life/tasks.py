"""
Life Integration — Task Management
────────────────────────────────────
Personal task tracker with priorities, tags, due dates.
Stored in SQLite locally + synced to Firestore.

Designed to be the action layer of your life — not just a to-do list.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Literal

import aiosqlite

from skills.base import BaseSkill
from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.skill.tasks")
cfg = get_config()

DB_PATH = cfg.base_dir / cfg.local_db_path


@dataclass
class Task:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:10])
    title: str = ""
    description: str = ""
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    status: Literal["todo", "in_progress", "done", "cancelled"] = "todo"
    tags: list[str] = field(default_factory=list)
    due_date: str = ""          # ISO date
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: float = 0
    context: str = ""           # "work" | "personal" | "project"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tags"] = json.dumps(d["tags"])
        return d

    @classmethod
    def from_row(cls, row: dict) -> "Task":
        row = dict(row)
        row["tags"] = json.loads(row.get("tags", "[]"))
        return cls(**{k: v for k, v in row.items() if k in cls.__dataclass_fields__})


class TasksSkill(BaseSkill):
    name = "tasks"
    description = "Manage personal tasks with priorities, tags, and due dates"

    tool_definition = {
        "name": "tasks",
        "description": (
            "Full task management system. "
            "Actions: create, list, update, complete, delete, search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "update", "complete", "delete", "search", "summary"],
                },
                "task_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "default": "medium",
                },
                "status": {
                    "type": "string",
                    "enum": ["todo", "in_progress", "done", "cancelled"],
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "due_date": {"type": "string", "description": "ISO date, e.g. 2025-12-31"},
                "context": {"type": "string", "description": "work | personal | project"},
                "query": {"type": "string"},
                "filter_status": {"type": "string"},
                "filter_priority": {"type": "string"},
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
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                title TEXT,
                description TEXT DEFAULT '',
                priority TEXT DEFAULT 'medium',
                status TEXT DEFAULT 'todo',
                tags TEXT DEFAULT '[]',
                due_date TEXT DEFAULT '',
                created_at REAL,
                updated_at REAL,
                completed_at REAL DEFAULT 0,
                context TEXT DEFAULT ''
            )
        """)
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON tasks(status)")
        await self._db.commit()

    async def run(self, action: str, **kwargs) -> Any:
        await self._ensure_db()
        handlers = {
            "create": self._create,
            "list": self._list,
            "update": self._update,
            "complete": self._complete,
            "delete": self._delete,
            "search": self._search,
            "summary": self._summary,
        }
        fn = handlers.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}"}
        return await fn(**kwargs)

    async def _create(self, title: str = "", **kwargs) -> dict:
        if not title:
            return {"error": "title is required"}
        task = Task(
            title=title,
            description=kwargs.get("description", ""),
            priority=kwargs.get("priority", "medium"),
            tags=kwargs.get("tags", []),
            due_date=kwargs.get("due_date", ""),
            context=kwargs.get("context", ""),
        )
        d = task.to_dict()
        await self._db.execute(
            "INSERT INTO tasks VALUES (:task_id,:title,:description,:priority,:status,:tags,:due_date,:created_at,:updated_at,:completed_at,:context)",
            d,
        )
        await self._db.commit()
        return {"success": True, "task_id": task.task_id, "title": title}

    async def _list(
        self,
        filter_status: str = "todo",
        filter_priority: str = "",
        context: str = "",
        **_,
    ) -> list[dict]:
        sql = "SELECT * FROM tasks WHERE 1=1"
        params: list = []
        if filter_status and filter_status != "all":
            sql += " AND status=?"
            params.append(filter_status)
        if filter_priority:
            sql += " AND priority=?"
            params.append(filter_priority)
        if context:
            sql += " AND context=?"
            params.append(context)
        sql += " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC LIMIT 50"

        async with self._db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def _update(self, task_id: str = "", **kwargs) -> dict:
        if not task_id:
            return {"error": "task_id required"}
        allowed = ["title", "description", "priority", "status", "due_date", "context"]
        sets = []
        params = []
        for k in allowed:
            if k in kwargs:
                sets.append(f"{k}=?")
                params.append(kwargs[k])
        if "tags" in kwargs:
            sets.append("tags=?")
            params.append(json.dumps(kwargs["tags"]))
        if not sets:
            return {"error": "Nothing to update"}
        sets.append("updated_at=?")
        params.append(time.time())
        params.append(task_id)
        await self._db.execute(f"UPDATE tasks SET {','.join(sets)} WHERE task_id=?", params)
        await self._db.commit()
        return {"success": True, "task_id": task_id}

    async def _complete(self, task_id: str = "", **_) -> dict:
        now = time.time()
        await self._db.execute(
            "UPDATE tasks SET status='done', completed_at=?, updated_at=? WHERE task_id=?",
            (now, now, task_id),
        )
        await self._db.commit()
        return {"success": True, "task_id": task_id, "status": "done"}

    async def _delete(self, task_id: str = "", **_) -> dict:
        await self._db.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
        await self._db.commit()
        return {"success": True}

    async def _search(self, query: str = "", **_) -> list[dict]:
        pattern = f"%{query}%"
        async with self._db.execute(
            "SELECT * FROM tasks WHERE title LIKE ? OR description LIKE ? ORDER BY updated_at DESC LIMIT 20",
            (pattern, pattern),
        ) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def _summary(self, **_) -> dict:
        stats: dict[str, int] = {}
        for status in ("todo", "in_progress", "done", "cancelled"):
            async with self._db.execute("SELECT COUNT(*) FROM tasks WHERE status=?", (status,)) as cur:
                row = await cur.fetchone()
                stats[status] = row[0] if row else 0

        # Overdue tasks
        today = time.strftime("%Y-%m-%d")
        async with self._db.execute(
            "SELECT * FROM tasks WHERE due_date != '' AND due_date < ? AND status NOT IN ('done','cancelled') ORDER BY due_date LIMIT 5",
            (today,),
        ) as cur:
            overdue = [dict(r) for r in await cur.fetchall()]

        # Critical
        async with self._db.execute(
            "SELECT * FROM tasks WHERE priority='critical' AND status='todo' LIMIT 5"
        ) as cur:
            critical = [dict(r) for r in await cur.fetchall()]

        return {
            "counts": stats,
            "overdue": overdue,
            "critical": critical,
            "total": sum(stats.values()),
        }
