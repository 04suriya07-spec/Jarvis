"""
Javris LLM — Circuit Breaker
──────────────────────────────
Prevents cascading failures to broken/quota-exhausted providers.

State machine:
  CLOSED    → normal, pass requests through
  OPEN      → provider is broken, reject immediately (no HTTP call)
  HALF_OPEN → cooling off finished, allow one probe request

Transition rules:
  CLOSED  →  OPEN      : N consecutive failures OR any 429
  OPEN    →  HALF_OPEN : after `open_timeout` seconds
  HALF_OPEN → CLOSED   : probe succeeded
  HALF_OPEN → OPEN     : probe failed (back-off doubles)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Awaitable, TypeVar

T = TypeVar("T")


class CBState(Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """
    Per-provider circuit breaker with exponential back-off on repeated opens.

    Parameters
    ──────────
    name               : display name for logging
    failure_threshold  : consecutive failures before opening
    open_timeout       : seconds to stay open before probing (doubles on re-open)
    max_open_timeout   : cap for exponential back-off
    """
    name: str
    failure_threshold: int   = 3
    open_timeout: float      = 30.0
    max_open_timeout: float  = 300.0   # 5 minutes max

    _state: CBState         = field(default=CBState.CLOSED, init=False, repr=False)
    _failures: int          = field(default=0,              init=False, repr=False)
    _opened_at: float       = field(default=0.0,            init=False, repr=False)
    _current_timeout: float = field(default=0.0,            init=False, repr=False)
    _probe_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    # ── State queries ──────────────────────────────────────────────

    @property
    def state(self) -> CBState:
        self._maybe_transition()
        return self._state

    @property
    def available(self) -> bool:
        """True if the breaker will pass a request through."""
        return self.state in (CBState.CLOSED, CBState.HALF_OPEN)

    @property
    def seconds_until_retry(self) -> float:
        """0 if available now, else seconds remaining in OPEN state."""
        if self._state != CBState.OPEN:
            return 0.0
        remaining = self._current_timeout - (time.monotonic() - self._opened_at)
        return max(0.0, remaining)

    def _maybe_transition(self) -> None:
        if self._state == CBState.OPEN:
            if time.monotonic() - self._opened_at >= self._current_timeout:
                self._state = CBState.HALF_OPEN

    # ── Event handlers ─────────────────────────────────────────────

    def on_success(self) -> None:
        """Call when a request succeeds."""
        self._failures = 0
        if self._state == CBState.HALF_OPEN:
            # Full recovery — reset back-off
            self._state = CBState.CLOSED
            self._current_timeout = self.open_timeout

    def on_failure(self) -> None:
        """Call when a request fails with a non-quota error."""
        self._failures += 1
        if self._failures >= self.failure_threshold or self._state == CBState.HALF_OPEN:
            self._open()

    def on_rate_limit(self, retry_after: float = 60.0) -> None:
        """
        Call when provider responds with 429.
        Opens circuit for exactly `retry_after` seconds (or 60s if unknown).
        """
        self._open(duration=retry_after)

    def on_timeout(self) -> None:
        """Call when request times out — counts as failure."""
        self.on_failure()

    def _open(self, duration: float | None = None) -> None:
        if duration is not None:
            self._current_timeout = min(duration, self.max_open_timeout)
        elif self._current_timeout == 0.0:
            # First open — use base timeout (no back-off yet)
            self._current_timeout = self.open_timeout
        else:
            # Subsequent opens — exponential back-off, capped at max
            self._current_timeout = min(self._current_timeout * 2, self.max_open_timeout)

        self._state  = CBState.OPEN
        self._opened_at = time.monotonic()
        self._failures = 0

    # ── Context manager for wrapping calls ────────────────────────

    async def call(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        timeout: float | None = None,
    ) -> T:
        """
        Execute `fn` inside the circuit breaker.
        Raises RuntimeError if circuit is OPEN.
        """
        if not self.available:
            raise CircuitOpenError(
                self.name, self.seconds_until_retry
            )

        try:
            if timeout:
                result = await asyncio.wait_for(fn(), timeout=timeout)
            else:
                result = await fn()
            self.on_success()
            return result
        except asyncio.CancelledError:
            # External cancellation — not a provider fault, don't penalise
            raise
        except RateLimitError as e:
            self.on_rate_limit(e.retry_after)
            raise
        except (asyncio.TimeoutError, TimeoutError):
            self.on_timeout()
            raise
        except Exception:
            self.on_failure()
            raise

    def reset(self) -> None:
        """Manually reset to CLOSED (admin use)."""
        self._state = CBState.CLOSED
        self._failures = 0
        self._current_timeout = self.open_timeout

    def __repr__(self) -> str:
        extra = ""
        if self._state == CBState.OPEN:
            extra = f" retry_in={self.seconds_until_retry:.0f}s"
        return f"<CB:{self.name} {self.state.value}{extra}>"


# ── Custom exceptions ──────────────────────────────────────────────

class CircuitOpenError(Exception):
    def __init__(self, provider: str, retry_in: float):
        self.provider = provider
        self.retry_in = retry_in
        super().__init__(f"Circuit OPEN for {provider!r} — retry in {retry_in:.0f}s")


class RateLimitError(Exception):
    def __init__(self, provider: str, retry_after: float = 60.0):
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(f"Rate limited by {provider!r} — retry after {retry_after:.0f}s")
