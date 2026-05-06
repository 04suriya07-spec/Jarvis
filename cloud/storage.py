"""
Javris Cloud Storage – Firebase Firestore
──────────────────────────────────────────
Stores:
  • Conversation sessions & messages
  • User facts / memory
  • Scheduled tasks
  • Activity logs

Schema:
  /users/{uid}/sessions/{session_id}/messages/{msg_id}
  /users/{uid}/facts/{fact_id}
  /users/{uid}/tasks/{task_id}
  /users/{uid}/activity/{log_id}
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from core.config import get_config
from core.logger import get_logger

logger = get_logger("javris.cloud")
cfg = get_config()

# User ID: use machine hostname or a fixed UUID stored locally
_UID_FILE = cfg.base_dir / "data" / ".uid"


def _get_or_create_uid() -> str:
    _UID_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _UID_FILE.exists():
        return _UID_FILE.read_text().strip()
    uid = str(uuid.uuid4())
    _UID_FILE.write_text(uid)
    return uid


UID = _get_or_create_uid()


class FirestoreStorage:
    """
    Async-friendly wrapper around firebase-admin Firestore.
    All I/O is run in a thread-pool executor because
    the firebase-admin SDK is synchronous.
    """

    def __init__(self):
        self._db = None
        self._available = False

    # ── Init ─────────────────────────────────────────────────

    def init(self) -> bool:
        """Initialise Firebase app. Returns True on success."""
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore

            if not firebase_admin._apps:
                cred = self._load_credentials()
                if cred is None:
                    logger.warning(
                        "Firebase credentials not found. Cloud sync disabled."
                    )
                    return False
                firebase_admin.initialize_app(cred)

            self._db = firestore.client()
            self._available = True
            logger.info(f"Firebase connected | project={cfg.firebase_project_id} | uid={UID}")
            return True

        except Exception as e:
            logger.warning(f"Firebase init failed: {e}. Cloud sync disabled.")
            self._available = False
            return False

    def _load_credentials(self):
        """Load Firebase credentials from file or env base64."""
        from firebase_admin import credentials

        # Option 1: base64 env var
        if cfg.firebase_credentials_base64:
            raw = base64.b64decode(cfg.firebase_credentials_base64)
            data = json.loads(raw)
            return credentials.Certificate(data)

        # Option 2: JSON file
        cred_path = cfg.firebase_creds_path
        if cred_path.exists():
            return credentials.Certificate(str(cred_path))

        return None

    @property
    def available(self) -> bool:
        return self._available

    # ── User root ─────────────────────────────────────────────

    def _user_ref(self):
        return self._db.collection("users").document(UID)

    # ── Sessions & Messages ───────────────────────────────────

    def save_session(self, session_id: str, metadata: dict | None = None) -> None:
        if not self._available:
            return
        try:
            ref = self._user_ref().collection("sessions").document(session_id)
            ref.set(
                {"session_id": session_id, "started_at": time.time(), **(metadata or {})},
                merge=True,
            )
        except Exception as e:
            logger.debug(f"Cloud save_session failed: {e}")

    def save_message(self, session_id: str, message: dict) -> None:
        if not self._available:
            return
        try:
            self._user_ref() \
                .collection("sessions").document(session_id) \
                .collection("messages").document(message["message_id"]) \
                .set(message)
        except Exception as e:
            logger.debug(f"Cloud save_message failed: {e}")

    def get_sessions(self, limit: int = 20) -> list[dict]:
        if not self._available:
            return []
        try:
            docs = (
                self._user_ref()
                .collection("sessions")
                .order_by("started_at", direction="DESCENDING")
                .limit(limit)
                .stream()
            )
            return [d.to_dict() for d in docs]
        except Exception as e:
            logger.debug(f"Cloud get_sessions failed: {e}")
            return []

    def get_session_messages(self, session_id: str) -> list[dict]:
        if not self._available:
            return []
        try:
            docs = (
                self._user_ref()
                .collection("sessions").document(session_id)
                .collection("messages")
                .order_by("timestamp")
                .stream()
            )
            return [d.to_dict() for d in docs]
        except Exception as e:
            logger.debug(f"Cloud get_session_messages failed: {e}")
            return []

    # ── Facts ─────────────────────────────────────────────────

    def save_fact(self, fact_id: str, category: str, content: str, source: str = "assistant") -> None:
        if not self._available:
            return
        try:
            self._user_ref().collection("facts").document(fact_id).set({
                "fact_id": fact_id,
                "category": category,
                "content": content,
                "source": source,
                "updated_at": time.time(),
            }, merge=True)
        except Exception as e:
            logger.debug(f"Cloud save_fact failed: {e}")

    def get_facts(self, category: str | None = None) -> list[dict]:
        if not self._available:
            return []
        try:
            ref = self._user_ref().collection("facts")
            if category:
                ref = ref.where("category", "==", category)
            return [d.to_dict() for d in ref.stream()]
        except Exception as e:
            logger.debug(f"Cloud get_facts failed: {e}")
            return []

    # ── Activity Log ──────────────────────────────────────────

    def log_activity(self, action: str, detail: str = "", extra: dict | None = None) -> None:
        if not self._available:
            return
        try:
            log_id = str(uuid.uuid4())
            self._user_ref().collection("activity").document(log_id).set({
                "log_id": log_id,
                "action": action,
                "detail": detail,
                "timestamp": time.time(),
                **(extra or {}),
            })
        except Exception as e:
            logger.debug(f"Cloud log_activity failed: {e}")

    # ── Sync helper ───────────────────────────────────────────

    async def sync_session(self, session_id: str) -> None:
        """Push latest session state to Firestore (non-blocking background task)."""
        import asyncio
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.save_session, session_id, {})


class CloudStorage:
    """Public interface combining Firestore + future providers."""

    def __init__(self):
        self.firestore = FirestoreStorage()

    def init(self) -> bool:
        return self.firestore.init()

    @property
    def available(self) -> bool:
        return self.firestore.available

    def save_message(self, session_id: str, message: dict) -> None:
        self.firestore.save_message(session_id, message)

    def get_sessions(self, limit: int = 20) -> list[dict]:
        return self.firestore.get_sessions(limit)

    def get_session_messages(self, session_id: str) -> list[dict]:
        return self.firestore.get_session_messages(session_id)

    def save_fact(self, fact_id: str, category: str, content: str) -> None:
        self.firestore.save_fact(fact_id, category, content)

    def log_activity(self, action: str, detail: str = "") -> None:
        self.firestore.log_activity(action, detail)

    async def sync_session(self, session_id: str) -> None:
        await self.firestore.sync_session(session_id)
