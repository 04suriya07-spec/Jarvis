"""
Javris Memory System
────────────────────
• Short-term: in-process conversation ring-buffer
• Long-term: SQLite (local) + Firestore (cloud)
• Supports semantic search over past conversations
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Optional

import aiosqlite

from core.config import get_config
from core.logger import get_logger
from core.vector_memory import VectorMemory

logger = get_logger("javris.memory")
cfg = get_config()

DB_PATH = cfg.base_dir / cfg.local_db_path


@dataclass
class Message:
    role: str          # "user" | "assistant" | "system" | "tool"
    content: str
    timestamp: float = field(default_factory=time.time)
    session_id: str = ""
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict = field(default_factory=dict)

    def to_anthropic(self) -> dict:
        """Convert to Anthropic message format."""
        return {"role": self.role, "content": self.content}

    def to_dict(self) -> dict:
        return asdict(self)


class ShortTermMemory:
    """Rolling window of recent messages (in-process)."""

    def __init__(self, max_messages: int = 50):
        self._buffer: deque[Message] = deque(maxlen=max_messages)
        self._session_id = str(uuid.uuid4())

    @property
    def session_id(self) -> str:
        return self._session_id

    def add(self, role: str, content: str, **metadata) -> Message:
        msg = Message(
            role=role,
            content=content,
            session_id=self._session_id,
            metadata=metadata,
        )
        self._buffer.append(msg)
        return msg

    def get_history(self, last_n: int | None = None) -> list[Message]:
        msgs = list(self._buffer)
        if last_n:
            msgs = msgs[-last_n:]
        return msgs

    def to_anthropic_messages(self, last_n: int = 20) -> list[dict]:
        """Return only user/assistant messages for the Anthropic API."""
        history = self.get_history(last_n)
        return [
            m.to_anthropic()
            for m in history
            if m.role in ("user", "assistant")
        ]

    def clear(self) -> None:
        self._buffer.clear()
        self._session_id = str(uuid.uuid4())

    def __len__(self) -> int:
        return len(self._buffer)


class LongTermMemory:
    """Persistent memory backed by SQLite + optional Firestore sync."""

    def __init__(self):
        self._db: aiosqlite.Connection | None = None
        self._cloud = None  # injected after firebase init

    async def init(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(DB_PATH)
        await self._create_schema()
        logger.info(f"Long-term memory initialised at {DB_PATH}")

    async def _create_schema(self) -> None:
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at REAL,
                summary TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT,
                role TEXT,
                content TEXT,
                timestamp REAL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS facts (
                fact_id TEXT PRIMARY KEY,
                category TEXT,
                content TEXT,
                source TEXT,
                created_at REAL,
                updated_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
            CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(timestamp);
            CREATE INDEX IF NOT EXISTS idx_facts_cat ON facts(category);
        """)
        await self._db.commit()

    async def save_session(self, session_id: str) -> None:
        await self._db.execute(
            "INSERT OR IGNORE INTO sessions VALUES (?, ?, '')",
            (session_id, time.time()),
        )
        await self._db.commit()

    async def save_message(self, msg: Message) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO messages VALUES (?, ?, ?, ?, ?, ?)",
            (
                msg.message_id,
                msg.session_id,
                msg.role,
                msg.content,
                msg.timestamp,
                json.dumps(msg.metadata),
            ),
        )
        await self._db.commit()

    async def get_sessions(self, limit: int = 20) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return [dict(zip([c[0] for c in cur.description], r)) for r in rows]

    async def get_session_messages(self, session_id: str) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY timestamp",
            (session_id,),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(zip([c[0] for c in cur.description], r)) for r in rows]

    async def search_messages(self, query: str, limit: int = 10) -> list[dict]:
        """Simple full-text keyword search."""
        pattern = f"%{query}%"
        async with self._db.execute(
            "SELECT * FROM messages WHERE content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (pattern, limit),
        ) as cur:
            rows = await cur.fetchall()
            return [dict(zip([c[0] for c in cur.description], r)) for r in rows]

    async def save_fact(
        self,
        category: str,
        content: str,
        source: str = "assistant",
        fact_id: str | None = None,
    ) -> str:
        fid = fact_id or str(uuid.uuid4())
        now = time.time()
        await self._db.execute(
            "INSERT OR REPLACE INTO facts VALUES (?, ?, ?, ?, ?, ?)",
            (fid, category, content, source, now, now),
        )
        await self._db.commit()
        return fid

    async def get_facts(self, category: str | None = None) -> list[dict]:
        if category:
            async with self._db.execute(
                "SELECT * FROM facts WHERE category=? ORDER BY updated_at DESC",
                (category,),
            ) as cur:
                rows = await cur.fetchall()
        else:
            async with self._db.execute(
                "SELECT * FROM facts ORDER BY updated_at DESC"
            ) as cur:
                rows = await cur.fetchall()
        return [dict(zip([c[0] for c in cur.description], r)) for r in rows]

    async def close(self) -> None:
        if self._db:
            await self._db.close()


class MemoryManager:
    """Unified interface combining short-term + long-term + vector memory."""

    def __init__(self):
        self.short = ShortTermMemory(max_messages=60)
        self.long = LongTermMemory()
        self.vector = VectorMemory()
        self._initialized = False

    async def init(self) -> None:
        await self.long.init()
        await self.long.save_session(self.short.session_id)
        # Vector memory init is sync (ChromaDB) — run in thread to not block
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.vector.init)
        self._initialized = True
        logger.info(
            f"Memory ready — vector backend: {self.vector.backend} "
            f"({self.vector.count()} entries)"
        )

    async def add(self, role: str, content: str, **metadata) -> Message:
        msg = self.short.add(role, content, **metadata)
        if self._initialized:
            await self.long.save_message(msg)
            # Index user/assistant turns in vector memory for semantic recall
            if role in ("user", "assistant") and content.strip():
                asyncio.create_task(
                    self.vector.add(
                        content,
                        metadata={"role": role, "session_id": msg.session_id},
                        doc_id=msg.message_id,
                    )
                )
        return msg

    def get_context(self, last_n: int = 20) -> list[dict]:
        """Messages formatted for Anthropic API."""
        return self.short.to_anthropic_messages(last_n)

    async def search(self, query: str, semantic: bool = True) -> list[dict]:
        """Search memory — semantic (vector) first, keyword fallback."""
        if semantic and self._initialized:
            results = await self.vector.search(query, n_results=8)
            if results:
                return [
                    {
                        "content": r["text"],
                        "score": r["score"],
                        "role": r["metadata"].get("role", ""),
                        "session_id": r["metadata"].get("session_id", ""),
                    }
                    for r in results
                ]
        return await self.long.search_messages(query)

    async def semantic_search(self, query: str, n: int = 5) -> list[dict]:
        """Pure vector search — returns scored results."""
        return await self.vector.search(query, n_results=n)

    async def remember_fact(self, category: str, content: str) -> None:
        await self.long.save_fact(category, content)
        # Also index facts in vector memory
        await self.vector.add(
            content,
            metadata={"type": "fact", "category": category},
        )
        logger.info(f"Fact remembered [{category}]: {content[:80]}")

    def vector_stats(self) -> dict:
        return self.vector.stats()

    async def close(self) -> None:
        await self.long.close()
