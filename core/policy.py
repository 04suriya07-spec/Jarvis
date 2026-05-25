"""Risk classification and approval policy for Javris actions."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from core.config import get_config
from core.models import RiskLevel

cfg = get_config()


@dataclass
class PolicyDecision:
    allowed: bool
    risk: RiskLevel
    requires_approval: bool = False
    reason: str = ""
    action_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "risk": self.risk.value,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "action_hash": self.action_hash,
        }


class PolicyEngine:
    """Conservative default policy for an OS-style assistant."""

    def __init__(self):
        self._approvals: dict[str, float] = {}

    def action_hash(self, skill: str, params: dict[str, Any]) -> str:
        # For high-risk OS/code actions: hash on skill+action only so that
        # approving "system_control:take_screenshot" covers all calls to that
        # action regardless of extra params (target, etc.)
        risk = self.classify(skill, params)
        if risk in {RiskLevel.CONTROL_COMPUTER, RiskLevel.EXECUTE_CODE}:
            body = json.dumps({"skill": skill, "action": str(params.get("action", ""))}, sort_keys=True)
        else:
            body = json.dumps({"skill": skill, "params": params}, sort_keys=True, default=str)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    def classify(self, skill: str, params: dict[str, Any]) -> RiskLevel:
        name = skill.lower()
        action = str(params.get("action", "")).lower()

        if any(k in name for k in ("code_runner", "run_code")):
            return RiskLevel.EXECUTE_CODE
        if name in {"system_control", "computer", "browser_agent"}:
            return RiskLevel.CONTROL_COMPUTER
        if any(k in name for k in ("email", "telegram", "discord")) and action.startswith("send"):
            return RiskLevel.SEND_EXTERNAL
        if name == "email" and action in {"reply"}:
            return RiskLevel.SEND_EXTERNAL
        if action in {"delete", "remove", "trash", "kill", "shutdown", "reboot"}:
            return RiskLevel.DELETE_OR_DESTRUCTIVE
        if action in {"create", "update", "complete", "write", "save"}:
            return RiskLevel.WRITE_PRIVATE
        if any(k in name for k in ("finance", "trading", "purchase", "payment")) and action not in {"quote", "price", "news", "indicator", "sentiment", "macro"}:
            return RiskLevel.FINANCIAL_OR_PURCHASE
        if any(k in json.dumps(params, default=str).lower() for k in ("api_key", "token", "password", "secret")):
            return RiskLevel.CREDENTIAL_ACCESS
        return RiskLevel.READ_ONLY

    def requires_approval(self, risk: RiskLevel) -> bool:
        if cfg.javris_permission_mode == "open":
            return risk in {
                RiskLevel.DELETE_OR_DESTRUCTIVE,
                RiskLevel.FINANCIAL_OR_PURCHASE,
                RiskLevel.CREDENTIAL_ACCESS,
            }
        if cfg.javris_permission_mode == "strict":
            return risk != RiskLevel.READ_ONLY
        return risk in {
            RiskLevel.SEND_EXTERNAL,
            RiskLevel.CONTROL_COMPUTER,
            RiskLevel.EXECUTE_CODE,
            RiskLevel.DELETE_OR_DESTRUCTIVE,
            RiskLevel.FINANCIAL_OR_PURCHASE,
            RiskLevel.CREDENTIAL_ACCESS,
        }

    def approve(self, action_hash: str, ttl_seconds: int = 600) -> None:
        self._approvals[action_hash] = time.time() + ttl_seconds

    def evaluate(self, skill: str, params: dict[str, Any], *, preapproved: bool = False) -> PolicyDecision:
        risk = self.classify(skill, params)
        action_hash = self.action_hash(skill, params)
        if risk == RiskLevel.CREDENTIAL_ACCESS:
            return PolicyDecision(
                allowed=False,
                risk=risk,
                requires_approval=True,
                reason="Credential access is denied by default.",
                action_hash=action_hash,
            )

        needs_approval = self.requires_approval(risk)
        approved = preapproved or self._approvals.get(action_hash, 0) > time.time()
        if needs_approval and not approved:
            return PolicyDecision(
                allowed=False,
                risk=risk,
                requires_approval=True,
                reason=f"{risk.value} requires explicit approval.",
                action_hash=action_hash,
            )
        return PolicyDecision(
            allowed=True,
            risk=risk,
            requires_approval=needs_approval,
            reason="allowed",
            action_hash=action_hash,
        )


_policy: PolicyEngine | None = None


def get_policy_engine() -> PolicyEngine:
    global _policy
    if _policy is None:
        _policy = PolicyEngine()
    return _policy
