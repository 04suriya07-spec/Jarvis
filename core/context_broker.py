"""Context Broker to gather and filter context before LLM execution."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger("javris.context_broker")

@dataclass
class ContextItem:
    content: str
    source: str
    relevance_score: float = 1.0
    recency_score: float = 1.0
    trust_score: float = 1.0
    timestamp: float = field(default_factory=time.time)

@dataclass
class ContextBundle:
    items: list[ContextItem] = field(default_factory=list)

    def to_string(self) -> str:
        """Format the context bundle into a prompt-friendly string."""
        if not self.items:
            return ""
            
        lines = ["--- Context ---"]
        for item in sorted(self.items, key=lambda x: x.relevance_score, reverse=True):
            lines.append(f"[{item.source}] {item.content}")
        lines.append("---------------")
        return "\n".join(lines)

class ContextBroker:
    def __init__(self, memory_manager: Any | None = None):
        self.memory = memory_manager

    async def build_context(self, user_input: str, task_type: str = "chat", budget_tokens: int = 2000, risk_level: str = "read_only") -> ContextBundle:
        bundle = ContextBundle()
        
        # 1. Add short-term memory (recent conversation)
        if self.memory:
            recent_turns = self.memory.get_context(last_n=10)
            if recent_turns:
                history_text = "\n".join([f"{msg['role']}: {msg['content']}" for msg in recent_turns])
                bundle.items.append(
                    ContextItem(content=f"Recent Conversation:\n{history_text}", source="working_memory", relevance_score=0.9, trust_score=1.0)
                )

            # 2. Add semantic memory (past facts/episodes related to user input)
            semantic_results = await self.memory.search(user_input, semantic=True)
            if semantic_results:
                for res in semantic_results[:3]: # top 3
                    bundle.items.append(
                        ContextItem(content=res['content'], source="semantic_memory", relevance_score=res.get('score', 0.5), trust_score=0.9)
                    )

        # 3. Time context
        current_time = time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime())
        bundle.items.append(
            ContextItem(content=f"Current Time: {current_time}", source="system", relevance_score=1.0, trust_score=1.0)
        )

        return bundle

_broker: ContextBroker | None = None

def get_context_broker(memory_manager: Any | None = None) -> ContextBroker:
    global _broker
    if _broker is None:
        _broker = ContextBroker(memory_manager)
    return _broker
