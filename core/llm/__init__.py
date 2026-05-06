"""
core.llm — Intelligent LLM Router Package
──────────────────────────────────────────
Public API:

    from core.llm import LLMRouter

    router = LLMRouter(tools=[...], tool_dispatch=fn)
    router.init()

    text = await router.chat(messages, system)

    async for chunk in router.stream(messages, system):
        yield chunk
"""

from core.llm.router import LLMRouter
from core.llm.circuit_breaker import CircuitBreaker, CircuitOpenError, RateLimitError
from core.llm.health import ProviderHealth
from core.llm.cache import ResponseCache
from core.llm.providers import ProviderError

__all__ = [
    "LLMRouter",
    "CircuitBreaker",
    "CircuitOpenError",
    "RateLimitError",
    "ProviderHealth",
    "ResponseCache",
    "ProviderError",
]
