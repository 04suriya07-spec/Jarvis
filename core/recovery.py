"""Recovery engine for failed autonomous steps."""

from __future__ import annotations

from typing import Any
from core.models import PlanStep, SkillResult
from core.logger import get_logger

logger = get_logger("javris.recovery")

class RecoveryEngine:
    def __init__(self):
        pass

    async def recover(self, step: PlanStep, result: SkillResult) -> tuple[bool, SkillResult | None]:
        """
        Attempt to recover from a failed step.
        Returns a tuple: (recovered: bool, new_result: SkillResult | None)
        """
        logger.warning(f"Attempting recovery for step '{step.goal}'. Error: {result.error}")
        
        # Determine failure class based on error
        error_msg = str(result.error).lower()
        if "rate limit" in error_msg or "429" in error_msg:
            # wait and retry?
            logger.info("Rate limit detected. Recovery strategy: wait and retry (not implemented fully).")
            return False, None
            
        elif "timeout" in error_msg:
            logger.info("Timeout detected. Recovery strategy: retry once.")
            # In a full implementation, we might dispatch a retry task here
            return False, None
            
        elif "unauthorized" in error_msg or "credentials" in error_msg:
            logger.info("Auth failure. Recovery strategy: ask user to reconnect.")
            return False, None
            
        elif "policy" in error_msg or "approval" in error_msg or getattr(result, "error_type", "") == "policy_blocked":
            logger.info("Policy blocked. Recovery strategy: ask for approval or refuse.")
            return False, None
            
        logger.info("Unknown error. Recovery strategy: stop safely and preserve trace.")
        return False, None

_recovery: RecoveryEngine | None = None

def get_recovery_engine() -> RecoveryEngine:
    global _recovery
    if _recovery is None:
        _recovery = RecoveryEngine()
    return _recovery
