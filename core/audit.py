"""Append-only audit logging for Javris actions."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from core.config import get_config
from core.models import RiskLevel, SkillResult
from core.security.redaction import redact_value

cfg = get_config()


class AuditLog:
    def __init__(self, path: Path | None = None):
        self.path = path or (cfg.logs_dir / "audit.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(
        self,
        *,
        action: str,
        actor: str = "assistant",
        risk: RiskLevel | str = RiskLevel.READ_ONLY,
        trace_id: str = "",
        input_data: Any = None,
        result: SkillResult | dict | str | None = None,
        decision: str = "executed",
    ) -> str:
        audit_id = str(uuid.uuid4())
        payload = {
            "audit_id": audit_id,
            "trace_id": trace_id,
            "timestamp": time.time(),
            "actor": actor,
            "action": action,
            "risk": risk.value if isinstance(risk, RiskLevel) else str(risk),
            "decision": decision,
            "input": redact_value(input_data),
            "result": redact_value(
                result.model_dump() if isinstance(result, SkillResult) else result
            ),
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        return audit_id


_audit_log: AuditLog | None = None


def get_audit_log() -> AuditLog:
    global _audit_log
    if _audit_log is None:
        _audit_log = AuditLog()
    return _audit_log
