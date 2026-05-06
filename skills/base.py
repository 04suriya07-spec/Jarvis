"""Base class for all Javris skills."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseSkill(ABC):
    """All skills inherit from this. Each skill exposes a Claude tool definition."""

    name: str = ""
    description: str = ""
    tool_definition: dict | None = None

    @abstractmethod
    async def run(self, **kwargs) -> Any:
        """Execute the skill. Returns a serialisable result."""
        ...
