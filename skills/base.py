"""Base class for all Javris skills."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from core.models import SkillResult


class BaseSkill(ABC):
    """
    All skills inherit from this. Each skill exposes a tool definition.

    Existing skills may still return plain dict/list/string values. Assistant
    dispatch normalizes those values to SkillResult at the boundary.
    """

    name: str = ""
    description: str = ""
    tool_definition: dict | None = None

    @abstractmethod
    async def run(self, **kwargs) -> Any:
        """Execute the skill. Returns a serialisable result."""
        ...

    def normalize_result(self, raw: Any) -> SkillResult:
        return SkillResult.from_raw(raw)
