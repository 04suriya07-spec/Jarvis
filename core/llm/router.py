"""
Javris LLM — Intelligent Router
────────────────────────────────
High-level strategy:

  1. Cache lookup     — return instantly on exact match (0ms)
  2. UCB1 selection   — rank available providers by exploitation+exploration score
  3. Parallel hedge   — race top-2 providers via asyncio.wait(FIRST_COMPLETED)
                        cancel the loser the moment the winner returns
  4. Waterfall        — if both hedged providers fail, try remaining providers
                        sequentially (circuit-breaker skips broken ones instantly)
  5. Ollama fallback  — always available locally, no quota

Latency targets:
  Cache hit         : ~0 ms
  Cloud (warm)      : 200 – 800 ms  (hedged parallel race wins)
  Cloud (cold open) : 800 – 1500 ms
  Ollama (GPU)      : 500 – 2000 ms
  Ollama (CPU)      : 1000 – 5000 ms

Circuit breaker prevents waiting on dead providers — broken provider
is skipped in <1 ms instead of waiting 30s for a timeout.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator, Callable, List, Optional, Tuple

from core.config import get_config
from core.logger import get_logger
from core.llm.cache import ResponseCache
from core.llm.circuit_breaker import CircuitBreaker, CircuitOpenError, RateLimitError
from core.llm.health import ProviderHealth
from core.llm.providers import (
    ClaudeProvider,
    CerebrasProvider,
    GeminiProvider,
    GoogleKeyPool,
    GroqProvider,
    OllamaProvider,
    OpenAIProvider,
    ProviderError,
)

logger = get_logger("javris.llm.router")
cfg    = get_config()


# ── Named provider slot ───────────────────────────────────────────

class _ProviderSlot:
    """Bundles a provider impl with its circuit breaker and health tracker."""
    def __init__(self, name: str, provider, priority: int):
        self.name     = name
        self.provider = provider
        self.priority = priority              # lower = prefer
        self.cb       = CircuitBreaker(name=name, failure_threshold=3, open_timeout=30.0)
        self.health   = ProviderHealth(name=name)

    @property
    def available(self) -> bool:
        return self.cb.available

    def ucb1_score(self) -> float:
        if not self.available:
            return -1.0
        return self.health.ucb1_score()

    def __repr__(self) -> str:
        return f"<Slot:{self.name} ucb1={self.ucb1_score():.3f} cb={self.cb.state.value}>"


# ── Router ────────────────────────────────────────────────────────

class LLMRouter:
    """
    Drop-in replacement for the old _call_llm / _call_openai / … methods.

    Usage::

        router = LLMRouter(tools=skill_tool_definitions, tool_dispatch=fn)
        await router.init()

        # non-streaming
        text = await router.chat(messages, system_prompt)

        # streaming
        async for token in router.stream(messages, system_prompt):
            yield token
    """

    def __init__(
        self,
        tools: Optional[List[dict]] = None,
        tool_dispatch: Optional[Callable] = None,
    ):
        self._tools         = tools or []
        self._tool_dispatch = tool_dispatch
        self._slots: List[_ProviderSlot] = []
        self._cache  = ResponseCache(max_size=256, ttl=300.0)
        self._ready  = False

    # ── Init ──────────────────────────────────────────────────────

    def init(self) -> None:
        """Build provider slots from available API keys. Call once at startup."""
        if self._ready:
            return

        priority = 0

        # Groq — fastest, goes first
        if cfg.groq_api_key:
            self._slots.append(_ProviderSlot(
                "groq",
                GroqProvider(cfg.groq_api_key),
                priority,
            ))
            priority += 1

        # Cerebras — second fastest
        if cfg.cerebras_api_key:
            self._slots.append(_ProviderSlot(
                "cerebras",
                CerebrasProvider(cfg.cerebras_api_key),
                priority,
            ))
            priority += 1

        if cfg.openai_api_key:
            self._slots.append(_ProviderSlot(
                "openai",
                OpenAIProvider(cfg.openai_api_key),
                priority,
            ))
            priority += 1

        google_keys = [
            k for k in [
                cfg.google_api_key_1,
                cfg.google_api_key_2,
                cfg.google_api_key_3,
                cfg.google_api_key,   # legacy single-key fallback
            ] if k
        ]
        # Deduplicate while preserving order
        seen: set[str] = set()
        google_keys = [k for k in google_keys if not (k in seen or seen.add(k))]

        if google_keys:
            pool = GoogleKeyPool(google_keys)
            self._slots.append(_ProviderSlot(
                "gemini",
                GeminiProvider(pool),
                priority,
            ))
            logger.info(f"Gemini key pool: {len(google_keys)} key(s) loaded")
            priority += 1

        if cfg.anthropic_api_key:
            self._slots.append(_ProviderSlot(
                "claude",
                ClaudeProvider(
                    api_key=cfg.anthropic_api_key,
                    model=cfg.javris_claude_model,
                    tools=self._tools,
                ),
                priority,
            ))
            priority += 1

        # Ollama is always added — it's the offline safety net
        self._slots.append(_ProviderSlot(
            "ollama",
            OllamaProvider(cfg.ollama_base_url, cfg.javris_ollama_model),
            priority,
        ))

        preferred = [
            cfg.javris_primary_model,
            "groq",
            "cerebras",
            "openai",
            "gemini",
            "claude",
            "ollama",
        ]
        ordered_names = []
        for name in preferred:
            if name not in ordered_names:
                ordered_names.append(name)
        priority_map = {name: idx for idx, name in enumerate(ordered_names)}
        for slot in self._slots:
            slot.priority = priority_map.get(slot.name, len(priority_map))
        self._slots.sort(key=lambda s: s.priority)

        self._ready = True
        names = [s.name for s in self._slots]
        logger.info(f"LLMRouter ready — providers: {names}")

    # ── Ranking ───────────────────────────────────────────────────

    def _ranked_slots(self) -> List[_ProviderSlot]:
        """Return available slots sorted by UCB1 score (desc)."""
        available = [s for s in self._slots if s.available]
        return sorted(
            available,
            key=lambda s: (s.ucb1_score(), -s.priority),
            reverse=True,
        )

    # ── Single provider call ──────────────────────────────────────

    async def _call_slot(
        self,
        slot: _ProviderSlot,
        messages: List[dict],
        system: str,
        max_tokens: int,
    ) -> Tuple[str, int]:
        """
        Call one provider through its circuit breaker.
        Returns (text, tokens) or raises.
        """
        t0 = time.monotonic()

        async def _do():
            if slot.name == "claude":
                return await slot.provider.chat(
                    messages, system, max_tokens,
                    tool_dispatch=self._tool_dispatch,
                )
            if slot.name in ("groq", "cerebras", "openai") and self._tools and self._tool_dispatch:
                return await slot.provider.chat(
                    messages, system, max_tokens,
                    tools=self._tools,
                    tool_dispatch=self._tool_dispatch,
                )
            return await slot.provider.chat(messages, system, max_tokens)

        # Ollama runs locally on CPU — needs much more time than cloud providers
        timeout = 120.0 if slot.name == "ollama" else 20.0

        try:
            text, tokens = await slot.cb.call(_do, timeout=timeout)
            latency = time.monotonic() - t0
            slot.health.record_success(latency, tokens)
            logger.debug(f"[{slot.name}] OK {latency*1000:.0f}ms {tokens}tok")
            return text, tokens

        except RateLimitError as e:
            slot.health.record_failure(is_rate_limit=True, retry_after=e.retry_after)
            logger.warning(f"[{slot.name}] Rate-limited — retry in {e.retry_after:.0f}s")
            raise

        except CircuitOpenError as e:
            logger.debug(f"[{slot.name}] Circuit OPEN — skipping (retry in {e.retry_in:.0f}s)")
            raise

        except asyncio.TimeoutError:
            slot.health.record_failure()
            logger.warning(f"[{slot.name}] Timeout after {timeout:.0f}s")
            raise ProviderError(slot.name, f"Request timed out after {timeout:.0f}s")

        except ProviderError:
            slot.health.record_failure()
            raise

        except Exception as e:
            slot.health.record_failure()
            raise ProviderError(slot.name, str(e)) from e

    # ── Parallel hedge ────────────────────────────────────────────

    async def _hedge(
        self,
        slots: List[_ProviderSlot],
        messages: List[dict],
        system: str,
        max_tokens: int,
    ) -> Tuple[str, int, str]:
        """
        Race top-2 providers via asyncio.wait(FIRST_COMPLETED).
        Returns (text, tokens, winner_name).
        Cancels the losing task immediately.
        """
        top = slots[:2]
        rest = slots[2:]

        tasks = {
            asyncio.create_task(
                self._call_slot(s, messages, system, max_tokens),
                name=s.name,
            ): s
            for s in top
        }

        while tasks:
            done, pending = await asyncio.wait(
                tasks.keys(), return_when=asyncio.FIRST_COMPLETED
            )
            winner_task = done.pop()

            # A task that was externally cancelled has no result/exception — skip it
            if winner_task.cancelled():
                del tasks[winner_task]
                for t in pending:
                    t.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                raise asyncio.CancelledError()

            exc = winner_task.exception()
            if exc is None:
                text, tokens = winner_task.result()
                # Reject suspiciously short responses (rate-limit error bleed-through)
                if tokens < 5 and text and len(text.strip()) < 20:
                    logger.warning(f"[{tasks[winner_task].name}] response too short ({tokens} tok) — treating as failure")
                    del tasks[winner_task]
                    continue
                winner_name = tasks[winner_task].name
                for t in pending:
                    t.cancel()
                # Drain losers so they don't leak
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                return text, tokens, winner_name

            logger.debug(f"[{tasks[winner_task].name}] hedged request failed: {exc}")
            del tasks[winner_task]
            continue

        for slot in rest:
            if not slot.available:
                continue
            try:
                # Shield from outer cancellation so Ollama gets a fair shot
                text, tokens = await asyncio.shield(
                    self._call_slot(slot, messages, system, max_tokens)
                )
                if tokens < 5 and text and len(text.strip()) < 20:
                    logger.warning(f"[{slot.name}] waterfall response too short ({tokens} tok) — skipping")
                    continue
                return text, tokens, slot.name
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.debug(f"[{slot.name}] fallback request failed: {e}")
                continue

        raise ProviderError("all", "All providers failed")

    # ── Public: chat ─────────────────────────────────────────────

    async def chat(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
    ) -> str:
        """
        Get a response using the full routing strategy.
        Never raises — returns an error string if everything fails.
        """
        if not self._ready:
            self.init()

        # 1. Cache lookup
        cached = self._cache.get(messages, system)
        if cached:
            logger.debug("Cache HIT")
            return cached

        # 2. Rank available providers
        ranked = self._ranked_slots()
        if not ranked:
            return "All AI providers are currently unavailable. Please try again in a moment."

        # 3. Parallel hedge + waterfall
        try:
            text, tokens, winner = await self._hedge(ranked, messages, system, max_tokens)
            logger.info(f"Response from [{winner}] — {tokens} tokens")

            # 4. Cache the result
            await self._cache.put(messages, system, text)
            return text

        except asyncio.CancelledError:
            # Propagate — caller (assistant.chat) handles graceful shutdown
            raise

        except Exception as e:
            logger.error(f"Router: all providers failed — {e}")
            return (
                "I'm having trouble reaching my AI backend right now. "
                "Please check your network connection or API keys and try again."
            )

    # ── Public: stream ────────────────────────────────────────────

    async def stream(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """
        Streaming response. Falls back gracefully:
          1. Try cloud providers with streaming
          2. Fall back to non-streaming chat() and yield as single chunk
        """
        if not self._ready:
            self.init()

        # Cache hit — yield full cached response as one chunk
        cached = self._cache.get(messages, system)
        if cached:
            logger.debug("Stream cache HIT")
            yield cached
            return

        ranked = self._ranked_slots()
        if not ranked:
            yield "All AI providers are currently unavailable."
            return

        # Try providers in UCB1 order for streaming
        full_text = ""
        for slot in ranked:
            if not slot.available:
                continue
            t0 = time.monotonic()
            try:
                stream_kwargs = {}
                if slot.name == "claude" and self._tools and self._tool_dispatch:
                    stream_kwargs["tool_dispatch"] = self._tool_dispatch
                async for chunk in slot.provider.stream(messages, system, max_tokens, **stream_kwargs):
                    full_text += chunk
                    yield chunk
                # Success
                latency = time.monotonic() - t0
                slot.health.record_success(latency, len(full_text) // 4)
                slot.cb.on_success()
                logger.info(f"Stream from [{slot.name}] {latency*1000:.0f}ms")
                # Cache full response
                await self._cache.put(messages, system, full_text)
                return

            except RateLimitError as e:
                slot.health.record_failure(is_rate_limit=True, retry_after=e.retry_after)
                slot.cb.on_rate_limit(e.retry_after)
                logger.warning(f"[{slot.name}] stream rate-limited")

            except asyncio.CancelledError:
                raise   # propagate — don't swallow genuine cancellation

            except (ProviderError, CircuitOpenError, Exception) as e:
                slot.health.record_failure()
                slot.cb.on_failure()
                logger.warning(f"[{slot.name}] stream failed: {e}")

        if not full_text:
            yield await self.chat(messages, system, max_tokens=max_tokens)

    # ── Monitoring ────────────────────────────────────────────────

    def health_report(self) -> dict:
        """Returns a dict suitable for /api/llm/health."""
        routing_order = [s.name for s in self._ranked_slots()]
        return {
            "providers": [
                {
                    **s.health.to_dict(),
                    "circuit_breaker": s.cb.state.value,
                    "retry_in_s": round(s.cb.seconds_until_retry, 1),
                    "ucb1_score": round(s.ucb1_score(), 4),
                }
                for s in self._slots
            ],
            "cache": self._cache.stats(),
            "routing_order": routing_order,
            "active_provider": routing_order[0] if routing_order else "",
        }

    async def invalidate_cache(self) -> None:
        await self._cache.invalidate()

    def reset_circuit(self, provider_name: str) -> bool:
        """Manually reset a provider's circuit breaker (admin)."""
        for slot in self._slots:
            if slot.name == provider_name:
                slot.cb.reset()
                return True
        return False
