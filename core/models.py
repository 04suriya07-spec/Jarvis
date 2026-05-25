"""Shared execution models for Javris."""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    WRITE_PRIVATE = "write_private"
    SEND_EXTERNAL = "send_external"
    CONTROL_COMPUTER = "control_computer"
    EXECUTE_CODE = "execute_code"
    DELETE_OR_DESTRUCTIVE = "delete_or_destructive"
    FINANCIAL_OR_PURCHASE = "financial_or_purchase"
    CREDENTIAL_ACCESS = "credential_access"


class SkillResult(BaseModel):
    ok: bool
    data: Any = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: Any) -> "SkillResult":
        if isinstance(raw, SkillResult):
            return raw
        if isinstance(raw, dict) and raw.get("error"):
            return cls(ok=False, data=raw, error=str(raw.get("error")), metadata={})
        return cls(ok=True, data=raw, metadata={})

    @classmethod
    def success(cls, data: Any) -> "SkillResult":
        return cls(ok=True, data=data)

    @classmethod
    def fail(cls, error: str) -> "SkillResult":
        return cls(ok=False, error=error)


class PlanStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    goal: str
    skill: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    risk: RiskLevel = RiskLevel.READ_ONLY
    requires_approval: bool = False


class ExecutionTrace(BaseModel):
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_goal: str = ""
    plan: list[PlanStep] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    final_result: SkillResult | None = None
    created_at: float = Field(default_factory=time.time)
