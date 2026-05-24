"""
Vector memory — semantic search over Javris long-term memory using ChromaDB.
Inspired by openclaw's Memory LanceDB / active-memory extensions.
Stores embeddings locally at data/vector_memory/ (no external service needed).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("javris.vector_memory")

_COLLECTION_NAME = "javris_memory"
_CHROMA_PATH = Path(__file__).resolve().parent.parent / "data" / "vector_memory"


class VectorMemory:
    """
    Semantic vector store backed by ChromaDB (local, persistent).

    Falls back to keyword search (BM25-style) when ChromaDB is unavailable,
    so the app keeps working without the extra dependency.
    """

    def __init__(self) -> None:
        self._collection: Any = None
        self._available = False
        self._fallback: list[dict] = []  # keyword fallback store

    # ── Initialisation ────────────────────────────────────────

    def init(self) -> None:
        """Initialise ChromaDB collection. Call once at startup (sync ok here)."""
        try:
            import chromadb  # type: ignore

            _CHROMA_PATH.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
            self._collection = client.get_or_create_collection(
                name=_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
            logger.info(
                f"VectorMemory: ChromaDB ready — {self._collection.count()} entries"
            )
        except ImportError:
            logger.warning(
                "VectorMemory: chromadb not installed — using keyword fallback. "
                "Run: pip install chromadb"
            )
        except Exception as e:
            logger.warning(f"VectorMemory: ChromaDB init failed ({e}) — using keyword fallback")

    # ── Write ─────────────────────────────────────────────────

    async def add(
        self,
        text: str,
        metadata: dict | None = None,
        doc_id: str | None = None,
    ) -> str:
        """Add a document to vector memory. Returns the doc_id used."""
        if not text or not text.strip():
            return ""

        _id = doc_id or _hash(text)
        meta = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "text_preview": text[:120],
            **(metadata or {}),
        }

        if self._available and self._collection is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: self._collection.upsert(
                    ids=[_id],
                    documents=[text],
                    metadatas=[meta],
                ),
            )
        else:
            # Keyword fallback — keep last 500 entries
            self._fallback.append({"id": _id, "text": text, "metadata": meta})
            if len(self._fallback) > 500:
                self._fallback = self._fallback[-500:]

        return _id

    # ── Query ─────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """
        Semantic search. Returns list of {text, metadata, distance} dicts.
        Falls back to keyword search when ChromaDB is unavailable.
        """
        if not query.strip():
            return []

        if self._available and self._collection is not None:
            try:
                loop = asyncio.get_running_loop()
                count = self._collection.count()
                if count == 0:
                    return []
                kwargs: dict = {"query_texts": [query], "n_results": min(n_results, count)}
                if where:
                    kwargs["where"] = where
                results = await loop.run_in_executor(
                    None, lambda: self._collection.query(**kwargs)
                )
                # chromadb 1.x returns a QueryResult object; 0.4.x returns a plain dict — handle both
                if hasattr(results, "documents"):
                    docs  = results.documents[0] if results.documents else []
                    metas = results.metadatas[0] if results.metadatas else []
                    dists = results.distances[0] if results.distances else []
                else:
                    docs  = results.get("documents", [[]])[0]
                    metas = results.get("metadatas",  [[]])[0]
                    dists = results.get("distances",  [[]])[0]
                return [
                    {"text": d, "metadata": m, "distance": dist, "score": round(1 - dist, 4)}
                    for d, m, dist in zip(docs, metas, dists)
                ]
            except Exception as e:
                logger.warning(f"VectorMemory search error: {e}")
                return []

        # Keyword fallback — simple term overlap scoring
        q_terms = set(query.lower().split())
        scored: list[tuple[float, dict]] = []
        for entry in self._fallback:
            text = entry["text"].lower()
            overlap = sum(1 for t in q_terms if t in text)
            if overlap:
                scored.append((overlap / len(q_terms), entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"text": e["text"], "metadata": e["metadata"], "distance": 1 - s, "score": round(s, 4)}
            for s, e in scored[:n_results]
        ]

    # ── Delete ────────────────────────────────────────────────

    async def delete(self, doc_id: str) -> None:
        """Remove a document by id."""
        if self._available and self._collection is not None:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: self._collection.delete(ids=[doc_id])
            )
        else:
            self._fallback = [e for e in self._fallback if e["id"] != doc_id]

    # ── Stats ─────────────────────────────────────────────────

    def count(self) -> int:
        if self._available and self._collection is not None:
            return self._collection.count()
        return len(self._fallback)

    @property
    def backend(self) -> str:
        return "chromadb" if self._available else "keyword_fallback"

    def stats(self) -> dict:
        return {
            "backend": self.backend,
            "count": self.count(),
            "path": str(_CHROMA_PATH) if self._available else None,
        }


# ── Helpers ───────────────────────────────────────────────────

def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
