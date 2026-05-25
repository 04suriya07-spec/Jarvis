"""Durable Task Ledger to store autonomous tasks and steps."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from core.db import get_db_manager

class TaskLedger:
    def __init__(self):
        self.db = get_db_manager()

    def create_task(self, goal: str, risk_level: str = "read_only", owner: str = "assistant") -> str:
        task_id = str(uuid.uuid4())
        now = time.time()
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tasks (task_id, goal, status, risk_level, created_at, updated_at, owner)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, goal, "pending", risk_level, now, now, owner)
            )
            conn.commit()
        return task_id

    def update_task_status(self, task_id: str, status: str, result_summary: str = "", error: str = "") -> None:
        now = time.time()
        completed_at = now if status in ("completed", "failed", "cancelled") else None
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, result_summary = ?, error = ?, updated_at = ?, completed_at = ?
                WHERE task_id = ?
                """,
                (status, result_summary, error, now, completed_at, task_id)
            )
            conn.commit()

    def add_step(self, task_id: str, step_index: int, action_type: str, tool_name: str, input_data: dict) -> str:
        step_id = str(uuid.uuid4())
        now = time.time()
        input_json = json.dumps(input_data, default=str)
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO task_steps (step_id, task_id, step_index, action_type, tool_name, input_json, status, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (step_id, task_id, step_index, action_type, tool_name, input_json, "running", now)
            )
            conn.commit()
        return step_id

    def complete_step(self, step_id: str, output_data: dict, status: str = "completed", error: str = "") -> None:
        now = time.time()
        output_json = json.dumps(output_data, default=str)
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE task_steps
                SET output_json = ?, status = ?, ended_at = ?, error = ?
                WHERE step_id = ?
                """,
                (output_json, status, now, error, step_id)
            )
            conn.commit()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    def get_task_steps(self, task_id: str) -> list[dict[str, Any]]:
        with self.db.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_index ASC", (task_id,))
            return [dict(row) for row in cursor.fetchall()]

_task_ledger: TaskLedger | None = None

def get_task_ledger() -> TaskLedger:
    global _task_ledger
    if _task_ledger is None:
        _task_ledger = TaskLedger()
    return _task_ledger
