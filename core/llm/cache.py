"""
Javris LLM — Response Cache
─────────────────────────────
Two-tier caching:

  L1 — Exact match (hash of last 3 messages + system prefix)
       LRU eviction, TTL=300s, max 256 entries

  L2 — Semantic similarity (not implemented here — placeholder for
       future embedding-based similarity matching)

Cache key: SHA-256(system_prefix_200 || last_3_message_contents)
           Truncated to 16 hex chars for compact storage.

Design:
  • Thread-safe: asyncio.Lock around all writes
  • Doesn't cache errors or empty responses
  • Doesn't cache very long responses (>4000 chars) — edge case, not worth the memory
  • Tracks hit_rate for monitoring via /api/llm/health
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from typing import List, Optional


class ResponseCache:
    """
    LRU cache with TTL for LLM responses.

    Usage::

        cache = ResponseCache(max_size=256, ttl=300)
        hit = cache.get(messages, system_prompt)
        if hit:
            return hit
        reply = await call_llm(...)
        cache.put(messages, system_prompt, reply)
    """

    def __init__(self, max_size: int = 256, ttl: float = 300.0):
        self._max    = max_size
        self._ttl    = ttl
        self._store: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._lock   = asyncio.Lock()
        self.hits    = 0
        self.misses  = 0
        self.evictions = 0

    # ── Cache key ─────────────────────────────────────────────────

    @staticmethod
    def _key(messages: List[dict], system: str) -> str:
        """Build a compact, stable cache key from recent messages + system prefix."""
        # Use only last 3 messages for key (beyond that, context affects response)
        recent_content = [
            (m.get("role", ""), str(m.get("content", ""))[:120])
            for m in messages[-3:]
        ]
        payload = system[:200] + "||" + str(recent_content)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    # ── Public API ────────────────────────────────────────────────

    def get(self, messages: List[dict], system: str) -> Optional[str]:
        """
        Synchronous fast-path lookup (no lock needed for reads
        since we check expiry atomically).
        """
        key = self._key(messages, system)
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        value, exp = entry
        if time.monotonic() > exp:
            # Stale — remove and miss
            self._store.pop(key, None)
            self.misses += 1
            return None
        # LRU: move to end
        self._store.move_to_end(key)
        self.hits += 1
        return value

    async def put(self, messages: List[dict], system: str, response: str) -> None:
        """Store a response (async for lock safety)."""
        if not response or len(response) > 4000:
            return   # don't cache empty or very long responses

        key = self._key(messages, system)
        async with self._lock:
            # Evict oldest if full
            while len(self._store) >= self._max:
                self._store.popitem(last=False)
                self.evictions += 1
            self._store[key] = (response, time.monotonic() + self._ttl)

    async def invalidate(self) -> None:
        """Clear all entries (e.g. when personality changes)."""
        async with self._lock:
            self._store.clear()

    def purge_expired(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.monotonic()
        dead = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in dead:
            del self._store[k]
        return len(dead)

    # ── Monitoring ────────────────────────────────────────────────

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    @property
    def size(self) -> int:
        return len(self._store)

    def stats(self) -> dict:
        return {
            "size":       self.size,
            "max_size":   self._max,
            "hits":       self.hits,
            "misses":     self.misses,
            "hit_rate":   round(self.hit_rate, 3),
            "evictions":  self.evictions,
            "ttl_s":      self._ttl,
        }
