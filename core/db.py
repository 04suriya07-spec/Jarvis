"""SQLite database connection and migrations."""

import sqlite3
from pathlib import Path
from typing import Generator
from contextlib import contextmanager
from core.config import get_config

cfg = get_config()

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        goal TEXT,
        status TEXT,
        risk_level TEXT,
        created_at REAL,
        updated_at REAL,
        completed_at REAL,
        owner TEXT,
        result_summary TEXT,
        error TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS task_steps (
        step_id TEXT PRIMARY KEY,
        task_id TEXT,
        step_index INTEGER,
        action_type TEXT,
        tool_name TEXT,
        input_json TEXT,
        output_json TEXT,
        status TEXT,
        started_at REAL,
        ended_at REAL,
        error TEXT,
        FOREIGN KEY (task_id) REFERENCES tasks(task_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_events (
        event_id TEXT PRIMARY KEY,
        correlation_id TEXT,
        actor TEXT,
        action TEXT,
        resource TEXT,
        decision TEXT,
        reason TEXT,
        timestamp REAL,
        payload_json TEXT
    );
    """
]

class DBManager:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or (cfg.data_dir / "javris.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self.get_connection() as conn:
            # Setup migration table
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
            )
            
            cursor = conn.execute("SELECT MAX(version) FROM schema_migrations")
            row = cursor.fetchone()
            current_version = row[0] if row and row[0] is not None else -1

            for i, migration in enumerate(MIGRATIONS):
                if i > current_version:
                    conn.execute(migration)
                    conn.execute("INSERT OR REPLACE INTO schema_migrations (version) VALUES (?)", (i,))
            conn.commit()

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

_db_manager: DBManager | None = None

def get_db_manager() -> DBManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DBManager()
    return _db_manager
