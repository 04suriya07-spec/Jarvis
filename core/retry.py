"""
Javris Retry + Cache Layer
──────────────────────────
Async exponential back-off decorator with in-memory TTL cache.

Usage:
    from core.retry import with_retry, cached

    @with_retry(max_retries=3, base_delay=1.0)
    async def fetch_weather(location: str) -> dict:
        ...

    @cached(ttl=600)  # 10-minute in-memory cache
    async def get_weather_cached(location: str) -> dict:
        ...

    # Combined (cache first, then retry on miss)
    @cached(ttl=600)
    @with_retry(max_retries=3)
    async def smart_fetch(location: str) -> dict:
        ...
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import random
import time
from typing import Any, Callable, TypeVar

from core.logger import get_logger

logger = get_logger("javris.retry")

F = TypeVar("F", bound=Callable[..., Any])

# ── Global in-memory cache ────────────────────────────────────────

_cache: dict[str, tuple[Any, float]] = {}   # key → (value, expires_at)


def _make_key(fn_name: str, args: tuple, kwargs: dict) -> str:
    """Build a stable cache key from function name + arguments."""
    raw = json.dumps({"fn": fn_name, "args": list(args), "kwargs": kwargs}, sort_keys=True, default=str)
    return hashlib.md5(raw.encode()).hexdigest()


def cache_get(key: str) -> tuple[bool, Any]:
    """Return (hit, value). Value is None on miss."""
    if key in _cache:
        value, expires_at = _cache[key]
        if time.time() < expires_at:
            return True, value
        del _cache[key]
    return False, None


def cache_set(key: str, value: Any, ttl: float) -> None:
    """Store value with TTL seconds expiry."""
    _cache[key] = (value, time.time() + ttl)


def cache_invalidate(prefix: str = "") -> int:
    """Remove all cache entries (or those whose key starts with prefix). Returns count."""
    if not prefix:
        count = len(_cache)
        _cache.clear()
        return count
    keys = [k for k in list(_cache.keys()) if k.startswith(prefix)]
    for k in keys:
        del _cache[k]
    return len(keys)


def cache_stats() -> dict:
    """Return stats about the in-memory cache."""
    now = time.time()
    live = sum(1 for _, (_, exp) in _cache.items() if exp > now)
    return {"total": len(_cache), "live": live, "expired": len(_cache) - live}


# ── Decorators ────────────────────────────────────────────────────

def with_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    exceptions: tuple = (Exception,),
    on_retry: Callable | None = None,
) -> Callable[[F], F]:
    """
    Async exponential back-off retry decorator.

    Args:
        max_retries:  Maximum number of retries (not counting initial attempt).
        base_delay:   Initial delay between retries in seconds.
        max_delay:    Maximum delay cap in seconds.
        jitter:       Add ±25% random jitter to avoid thundering herd.
        exceptions:   Tuple of exception types to catch and retry on.
        on_retry:     Optional callback(attempt, delay, exc) called before each retry.
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_retries:
                        break
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    if jitter:
                        delay *= 0.75 + random.random() * 0.5
                    logger.warning(
                        f"[retry] {fn.__name__} attempt {attempt + 1}/{max_retries + 1} "
                        f"failed: {exc}. Retrying in {delay:.1f}s…"
                    )
                    if on_retry:
                        try:
                            on_retry(attempt, delay, exc)
                        except Exception:
                            pass
                    await asyncio.sleep(delay)
            logger.error(f"[retry] {fn.__name__} exhausted all {max_retries + 1} attempts. Last error: {last_exc}")
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator


def cached(
    ttl: float = 300.0,
    key_fn: Callable | None = None,
    skip_on_error: bool = True,
) -> Callable[[F], F]:
    """
    In-memory TTL cache decorator for async functions.

    Args:
        ttl:           Cache TTL in seconds.
        key_fn:        Optional custom key function: key_fn(fn_name, args, kwargs) → str.
        skip_on_error: If True, don't cache results that look like error dicts
                       (i.e., dicts containing an "error" key).
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            if key_fn:
                key = key_fn(fn.__name__, args, kwargs)
            else:
                key = _make_key(fn.__name__, args, kwargs)

            hit, value = cache_get(key)
            if hit:
                logger.debug(f"[cache] HIT  {fn.__name__}  key={key[:12]}…")
                return value

            result = await fn(*args, **kwargs)

            # Don't cache error responses
            if skip_on_error and isinstance(result, dict) and "error" in result:
                logger.debug(f"[cache] SKIP {fn.__name__} (error result)")
                return result

            cache_set(key, result, ttl)
            logger.debug(f"[cache] SET  {fn.__name__}  ttl={ttl}s  key={key[:12]}…")
            return result
        return wrapper  # type: ignore[return-value]
    return decorator


# ── Convenience: cached + retry combined ─────────────────────────

def resilient(
    ttl: float = 300.0,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 20.0,
) -> Callable[[F], F]:
    """
    Shortcut that applies @cached then @with_retry — cache wins first,
    and if the underlying call is made, it gets retried automatically.

    Usage:
        @resilient(ttl=600, max_retries=3)
        async def get_weather(location: str):
            ...
    """
    def decorator(fn: F) -> F:
        retried = with_retry(max_retries=max_retries, base_delay=base_delay, max_delay=max_delay)(fn)
        return cached(ttl=ttl)(retried)  # type: ignore[return-value]
    return decorator
