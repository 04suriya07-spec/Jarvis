"""Verifier to check if a planned step succeeded."""

from __future__ import annotations

from typing import Any
from core.models import PlanStep, SkillResult
from core.logger import get_logger

logger = get_logger("javris.verifier")

class Verifier:
    def __init__(self):
        pass

    async def verify(self, step: PlanStep, result: SkillResult) -> bool:
        """
        Verify if the step actually succeeded.
        Returns True if verified, False if failed.
        """
        if not result.ok:
            logger.info(f"Verification failed: Result was not ok for step '{step.goal}'")
            return False

        # In the future, this can use an LLM or specific assertions per skill type
        # For now, if the skill reported success, we assume it's verified.
        
        logger.info(f"Verification passed for step '{step.goal}'")
        return True

_verifier: Verifier | None = None

def get_verifier() -> Verifier:
    global _verifier
    if _verifier is None:
        _verifier = Verifier()
    return _verifier
