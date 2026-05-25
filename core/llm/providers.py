"""
Javris LLM — Provider Implementations
──────────────────────────────────────
Unified async interface for all four providers:

  OpenAI   — GPT-4o-mini, streaming, proper 429 handling
  Gemini   — gemini-2.0-flash → lite rotation, strict alternation
  Claude   — claude-* via Anthropic SDK, tool-use loop
  Ollama   — local model, last-resort fallback

Each provider:
  • Returns (text, tokens_used) on success
  • Raises RateLimitError(retry_after) on 429
  • Raises ProviderError on other failures
  • Supports streaming via async generators

Design choices:
  • httpx.AsyncClient reused per-call (not per-provider) — keeps code
    simple without the complexity of connection pool lifecycle management
  • retry_after parsed from Retry-After header or response body
  • Tool-use loop lives in Claude provider (only Claude supports tools here)
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import AsyncIterator, List, Optional, Tuple

import httpx

from core.llm.circuit_breaker import RateLimitError

# Shared timeout config
_FAST_TIMEOUT   = httpx.Timeout(connect=5.0, read=20.0, write=5.0, pool=2.0)
_STREAM_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=5.0, pool=2.0)
# Gemini-specific: shorter connect so ConnectTimeout fails fast when blocked by firewall
_GEMINI_TIMEOUT = httpx.Timeout(connect=4.0, read=20.0, write=5.0, pool=2.0)


class ProviderError(Exception):
    """Non-quota provider failure (network, bad response, etc.)"""
    def __init__(self, provider: str, msg: str):
        self.provider = provider
        super().__init__(f"[{provider}] {msg}")


def _to_openai_tools(anthropic_tools: List[dict]) -> List[dict]:
    """Convert Anthropic tool format → OpenAI function-calling format."""
    result = []
    for t in anthropic_tools:
        result.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return result


# ── Retry-after header parsing ────────────────────────────────────

def _parse_retry_after(response: httpx.Response) -> float:
    """Extract retry-after seconds from 429 response headers or body."""
    # Standard header
    ra = response.headers.get("retry-after") or response.headers.get("Retry-After")
    if ra:
        try:
            return float(ra)
        except ValueError:
            pass

    # OpenAI puts it in the body JSON
    try:
        body = response.json()
        # OpenAI: {"error": {"message": "... Please retry after 20 seconds ..."}}
        msg = str(body.get("error", {}).get("message", ""))
        m = re.search(r"retry after (\d+)", msg, re.I)
        if m:
            return float(m.group(1))
    except Exception:
        pass

    return 60.0  # default


# ─────────────────────────────────────────────────────────────────
# OpenAI Provider
# ─────────────────────────────────────────────────────────────────

class OpenAIProvider:
    NAME = "openai"
    MODEL = "gpt-4o-mini"
    URL   = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str):
        self._key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
        stream: bool = False,
        tools: Optional[List[dict]] = None,
    ) -> dict:
        payload = {
            "model": self.MODEL,
            "messages": [{"role": "system", "content": system}] + messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    async def chat(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
        tools: Optional[List[dict]] = None,
        tool_dispatch=None,
    ) -> Tuple[str, int]:
        """Returns (text, tokens). Raises RateLimitError or ProviderError."""
        openai_tools = _to_openai_tools(tools) if tools else None
        history = [{"role": "system", "content": system}] + list(messages)
        total_tokens = 0

        for _ in range(6):
            payload = {
                "model": self.MODEL,
                "messages": history,
                "temperature": 0.7,
                "max_tokens": max_tokens,
            }
            if openai_tools:
                payload["tools"] = openai_tools
                payload["tool_choice"] = "auto"

            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                r = await client.post(self.URL, json=payload, headers=self._headers)

            if r.status_code == 429:
                raise RateLimitError(self.NAME, _parse_retry_after(r))
            if r.status_code != 200:
                raise ProviderError(self.NAME, f"HTTP {r.status_code}: {r.text[:200]}")

            data = r.json()
            choice = data["choices"][0]
            msg = choice["message"]
            total_tokens += data.get("usage", {}).get("completion_tokens", 0)

            if choice.get("finish_reason") == "tool_calls" and tool_dispatch and msg.get("tool_calls"):
                history.append(msg)
                tool_results = []
                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    try:
                        args = json.loads(fn["arguments"])
                    except Exception:
                        args = {}
                    result = await tool_dispatch(fn["name"], args)
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": str(result),
                    })
                history.extend(tool_results)
                continue

            text = msg.get("content") or ""
            return text, total_tokens

        raise ProviderError(self.NAME, "Tool-use loop exceeded max hops")

    async def stream(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        payload = self._build_payload(messages, system, max_tokens, stream=True)
        async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
            async with client.stream("POST", self.URL, json=payload, headers=self._headers) as r:
                if r.status_code == 429:
                    body = await r.aread()
                    raise RateLimitError(self.NAME, _parse_retry_after(
                        httpx.Response(429, headers=r.headers, content=body)
                    ))
                if r.status_code != 200:
                    body = await r.aread()
                    raise ProviderError(self.NAME, f"HTTP {r.status_code}")

                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        pass


# ─────────────────────────────────────────────────────────────────
# Google Key Pool — rotates across multiple API keys
# ─────────────────────────────────────────────────────────────────

class GoogleKeyPool:
    """
    Rotates across up to N Google API keys to prevent quota exhaustion.

    Strategy
    ────────
    • Round-robin: each request gets the next available key so load is
      spread evenly across all keys from the start.
    • RESOURCE_EXHAUSTED (daily quota): mark key exhausted for 1 hour,
      skip it immediately and try the next key.
    • RPM rate-limit (temporary): mark key cooling down for 60 s.
    • If all keys are exhausted, raises RateLimitError so the router
      can fall back to Claude / Ollama.
    """

    _COOLDOWN_QUOTA = 3_600.0   # 1 h cooldown on daily quota exhaustion
    _COOLDOWN_RPM   = 60.0      # 60 s cooldown on per-minute rate limit

    def __init__(self, keys: List[str]):
        self._keys: List[str] = [k for k in keys if k]
        if not self._keys:
            raise ValueError("GoogleKeyPool: at least one API key is required")
        self._exhausted_until: dict[str, float] = {}
        self._idx = 0
        self._lock = threading.Lock()

    # ── Key selection ─────────────────────────────────────────────

    def next_key(self) -> Optional[str]:
        """Return the next available (non-exhausted) key, or None."""
        with self._lock:
            now = time.time()
            for _ in range(len(self._keys)):
                key = self._keys[self._idx % len(self._keys)]
                self._idx += 1
                if self._exhausted_until.get(key, 0.0) <= now:
                    return key
        return None

    def all_keys_for_attempt(self) -> List[str]:
        """
        Return all non-exhausted keys starting from the current round-robin
        position. Used by chat() to iterate key → model combos.
        """
        now = time.time()
        with self._lock:
            start = self._idx % len(self._keys)
            ordered = self._keys[start:] + self._keys[:start]
            self._idx += 1          # advance so next request starts on a fresh key
        return [k for k in ordered if self._exhausted_until.get(k, 0.0) <= now]

    # ── Quota tracking ────────────────────────────────────────────

    def mark_quota_exhausted(self, key: str) -> None:
        """Daily quota hit — cool this key down for 1 hour."""
        with self._lock:
            self._exhausted_until[key] = time.time() + self._COOLDOWN_QUOTA

    def mark_rpm_limited(self, key: str, retry_after: float = _COOLDOWN_RPM) -> None:
        """Per-minute rate limit — short cooldown."""
        with self._lock:
            self._exhausted_until[key] = time.time() + retry_after

    # ── Status ────────────────────────────────────────────────────

    def status(self) -> dict:
        now = time.time()
        out = {}
        for k in self._keys:
            until = self._exhausted_until.get(k, 0.0)
            if until <= now:
                out[k[:12] + "..."] = "available"
            else:
                out[k[:12] + "..."] = f"exhausted ({int(until - now)}s remaining)"
        return out

    @property
    def available_count(self) -> int:
        now = time.time()
        return sum(1 for k in self._keys if self._exhausted_until.get(k, 0.0) <= now)


# ─────────────────────────────────────────────────────────────────
# Gemini Provider
# ─────────────────────────────────────────────────────────────────

class GeminiProvider:
    NAME = "gemini"
    _MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash"]
    _BASE   = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, key_pool: GoogleKeyPool):
        self._pool = key_pool

    @staticmethod
    def _url(model: str, key: str) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

    @staticmethod
    def _stream_url(model: str, key: str) -> str:
        return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={key}&alt=sse"

    @staticmethod
    def _is_quota_error(response: httpx.Response) -> bool:
        """True when the 429 is a daily quota exhaustion, not an RPM spike."""
        try:
            status = response.json().get("error", {}).get("status", "")
            return status == "RESOURCE_EXHAUSTED"
        except Exception:
            return False

    @staticmethod
    def _build_contents(messages: List[dict], system: str) -> List[dict]:
        """Gemini requires strict user/model alternation."""
        contents: List[dict] = []
        last_role: Optional[str] = None

        for m in messages:
            role = "user" if m.get("role") == "user" else "model"
            text = str(m.get("content", "")).strip()
            if not text:
                continue
            if role == last_role and contents:
                contents[-1]["parts"][0]["text"] += f"\n\n{text}"
            else:
                contents.append({"role": role, "parts": [{"text": text}]})
                last_role = role

        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

        contents[0]["parts"][0]["text"] = (
            f"[System]\n{system}\n\n" + contents[0]["parts"][0]["text"]
        )
        return contents

    async def chat(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
    ) -> Tuple[str, int]:
        """
        Try every (key, model) combination until one succeeds.

        Iteration order — models change faster than keys so we exhaust
        all model tiers on a key before moving to the next key:
          (Key1, flash) → (Key1, flash-lite) → (Key1, 2.5-flash)
          (Key2, flash) → (Key2, flash-lite) → (Key2, 2.5-flash)
          (Key3, flash) → (Key3, flash-lite) → (Key3, 2.5-flash)

        Important: each model has its OWN daily quota bucket on Google's
        side. gemini-2.5-flash stays alive even when flash / flash-lite
        are both exhausted. So we NEVER skip a key early — we always
        try every model on every key before giving up.
        """
        payload = {
            "contents": self._build_contents(messages, system),
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.5},
        }

        available_keys = self._pool.all_keys_for_attempt()
        if not available_keys:
            raise RateLimitError(self.NAME, self._pool._COOLDOWN_RPM)

        async with httpx.AsyncClient(timeout=_GEMINI_TIMEOUT) as client:
            for key in available_keys:
                all_models_failed = True
                for model in self._MODELS:
                    r = await client.post(self._url(model, key), json=payload)

                    if r.status_code == 200:
                        data = r.json()
                        try:
                            text = data["candidates"][0]["content"]["parts"][0]["text"]
                        except (KeyError, IndexError) as exc:
                            raise ProviderError(self.NAME, f"Unexpected response: {exc}")
                        tokens = data.get("usageMetadata", {}).get("candidatesTokenCount", 0)
                        return text, tokens

                    if r.status_code == 429:
                        # Whether quota or RPM, keep trying remaining models.
                        # Each model has its own quota bucket on Google's side.
                        if not self._is_quota_error(r):
                            self._pool.mark_rpm_limited(key, _parse_retry_after(r))
                        continue    # next model

                    # Other HTTP errors — skip this model
                    continue

                # All models on this key failed → mark key exhausted
                if all_models_failed:
                    self._pool.mark_quota_exhausted(key)

        raise RateLimitError(self.NAME, self._pool._COOLDOWN_QUOTA)

    async def stream(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Streaming via SSE. Rotates keys the same way as chat()."""
        payload = {
            "contents": self._build_contents(messages, system),
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.5},
        }

        available_keys = self._pool.all_keys_for_attempt()
        if not available_keys:
            raise RateLimitError(self.NAME, self._pool._COOLDOWN_RPM)

        for key in available_keys:
            for model in self._MODELS:
                try:
                    async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
                        async with client.stream(
                            "POST", self._stream_url(model, key), json=payload
                        ) as r:
                            if r.status_code == 429:
                                body = await r.aread()
                                try:
                                    is_quota = json.loads(body).get("error", {}).get("status", "") == "RESOURCE_EXHAUSTED"
                                except Exception:
                                    is_quota = False
                                if not is_quota:
                                    self._pool.mark_rpm_limited(key)
                                # Either way — keep trying other models (each has its own quota)
                                continue

                            if r.status_code != 200:
                                continue

                            async for line in r.aiter_lines():
                                if not line.startswith("data: "):
                                    continue
                                try:
                                    chunk = json.loads(line[6:])
                                    text = chunk["candidates"][0]["content"]["parts"][0]["text"]
                                    if text:
                                        yield text
                                except Exception:
                                    pass
                            return  # stream finished successfully

                except httpx.TimeoutException:
                    continue

            # All models on this key failed — mark key exhausted
            self._pool.mark_quota_exhausted(key)

        raise RateLimitError(self.NAME, self._pool._COOLDOWN_QUOTA)


# ─────────────────────────────────────────────────────────────────
# Claude Provider (Anthropic SDK)
# ─────────────────────────────────────────────────────────────────

class ClaudeProvider:
    NAME = "claude"

    def __init__(self, api_key: str, model: str, tools: Optional[List[dict]] = None):
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model  = model
        self._tools  = tools or []

    async def chat(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
        tool_dispatch=None,        # Optional[Callable[[str, dict], Awaitable[str]]]
    ) -> Tuple[str, int]:
        import anthropic

        params = dict(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=list(messages),
        )
        if self._tools:
            params["tools"] = self._tools

        max_hops = 6
        for _ in range(max_hops):
            try:
                response = await self._client.messages.create(**params)
            except anthropic.RateLimitError as e:
                raise RateLimitError(self.NAME, 60.0) from e
            except anthropic.APIError as e:
                raise ProviderError(self.NAME, str(e)) from e

            if response.stop_reason == "tool_use" and tool_dispatch:
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = await tool_dispatch(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(result),
                        })
                params["messages"].append({"role": "assistant", "content": list(response.content)})
                params["messages"].append({"role": "user",      "content": tool_results})
                continue

            text   = "\n".join(b.text for b in response.content if hasattr(b, "text")).strip()
            tokens = response.usage.output_tokens if response.usage else 0
            return text, tokens

        raise ProviderError(self.NAME, "Tool-use loop exceeded max hops")

    async def stream(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
        tool_dispatch=None,
    ) -> AsyncIterator[str]:
        import anthropic
        # When tools are configured, fall back to chat() so the tool-use
        # loop runs correctly. Yield the full response as one chunk.
        if self._tools and tool_dispatch:
            text, _ = await self.chat(messages, system, max_tokens, tool_dispatch=tool_dispatch)
            yield text
            return
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield text
        except anthropic.RateLimitError as e:
            raise RateLimitError(self.NAME, 60.0) from e
        except anthropic.APIError as e:
            raise ProviderError(self.NAME, str(e)) from e


# ─────────────────────────────────────────────────────────────────
# Groq Provider — fastest open-source inference (llama3, mixtral)
# ─────────────────────────────────────────────────────────────────

class GroqProvider:
    NAME  = "groq"
    MODEL = "llama-3.3-70b-versatile"   # best quality/speed balance on Groq
    URL   = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str):
        self._key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages, system, max_tokens, stream=False):
        return {
            "model": self.MODEL,
            "messages": [{"role": "system", "content": system}] + messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    async def chat(self, messages, system, max_tokens=1024, tools=None, tool_dispatch=None):
        openai_tools = _to_openai_tools(tools) if tools else None
        history = [{"role": "system", "content": system}] + list(messages)
        total_tokens = 0

        for _ in range(6):
            payload = {
                "model": self.MODEL,
                "messages": history,
                "temperature": 0.7,
                "max_tokens": max_tokens,
            }
            if openai_tools:
                payload["tools"] = openai_tools
                payload["tool_choice"] = "auto"

            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                r = await client.post(self.URL, json=payload, headers=self._headers)
            if r.status_code == 429:
                raise RateLimitError(self.NAME, _parse_retry_after(r))
            if r.status_code != 200:
                raise ProviderError(self.NAME, f"HTTP {r.status_code}: {r.text[:200]}")

            data = r.json()
            choice = data["choices"][0]
            msg = choice["message"]
            total_tokens += data.get("usage", {}).get("completion_tokens", 0)

            if choice.get("finish_reason") == "tool_calls" and tool_dispatch and msg.get("tool_calls"):
                history.append(msg)
                tool_results = []
                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    try:
                        args = json.loads(fn["arguments"])
                    except Exception:
                        args = {}
                    result = await tool_dispatch(fn["name"], args)
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": str(result),
                    })
                history.extend(tool_results)
                continue

            text = msg.get("content") or ""
            return text, total_tokens

        raise ProviderError(self.NAME, "Tool-use loop exceeded max hops")

    async def stream(self, messages, system, max_tokens=1024):
        async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
            async with client.stream("POST", self.URL, json=self._payload(messages, system, max_tokens, stream=True), headers=self._headers) as r:
                if r.status_code == 429:
                    body = await r.aread()
                    raise RateLimitError(self.NAME, _parse_retry_after(httpx.Response(429, headers=r.headers, content=body)))
                if r.status_code != 200:
                    body = await r.aread()
                    raise ProviderError(self.NAME, f"HTTP {r.status_code}")
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        pass


# ─────────────────────────────────────────────────────────────────
# Cerebras Provider — ultra-fast inference chip
# ─────────────────────────────────────────────────────────────────

class CerebrasProvider:
    NAME  = "cerebras"
    MODEL = "llama-3.3-70b"
    URL   = "https://api.cerebras.ai/v1/chat/completions"

    def __init__(self, api_key: str):
        self._key = api_key
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _payload(self, messages, system, max_tokens, stream=False):
        return {
            "model": self.MODEL,
            "messages": [{"role": "system", "content": system}] + messages,
            "temperature": 0.7,
            "max_tokens": max_tokens,
            "stream": stream,
        }

    async def chat(self, messages, system, max_tokens=1024, tools=None, tool_dispatch=None):
        openai_tools = _to_openai_tools(tools) if tools else None
        history = [{"role": "system", "content": system}] + list(messages)
        total_tokens = 0

        for _ in range(6):
            payload = {
                "model": self.MODEL,
                "messages": history,
                "temperature": 0.7,
                "max_tokens": max_tokens,
            }
            if openai_tools:
                payload["tools"] = openai_tools
                payload["tool_choice"] = "auto"

            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                r = await client.post(self.URL, json=payload, headers=self._headers)
            if r.status_code == 429:
                raise RateLimitError(self.NAME, _parse_retry_after(r))
            if r.status_code != 200:
                raise ProviderError(self.NAME, f"HTTP {r.status_code}: {r.text[:200]}")

            data = r.json()
            choice = data["choices"][0]
            msg = choice["message"]
            total_tokens += data.get("usage", {}).get("completion_tokens", 0)

            if choice.get("finish_reason") == "tool_calls" and tool_dispatch and msg.get("tool_calls"):
                history.append(msg)
                tool_results = []
                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    try:
                        args = json.loads(fn["arguments"])
                    except Exception:
                        args = {}
                    result = await tool_dispatch(fn["name"], args)
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": str(result),
                    })
                history.extend(tool_results)
                continue

            text = msg.get("content") or ""
            return text, total_tokens

        raise ProviderError(self.NAME, "Tool-use loop exceeded max hops")

    async def stream(self, messages, system, max_tokens=1024):
        async with httpx.AsyncClient(timeout=_STREAM_TIMEOUT) as client:
            async with client.stream("POST", self.URL, json=self._payload(messages, system, max_tokens, stream=True), headers=self._headers) as r:
                if r.status_code == 429:
                    body = await r.aread()
                    raise RateLimitError(self.NAME, _parse_retry_after(httpx.Response(429, headers=r.headers, content=body)))
                if r.status_code != 200:
                    body = await r.aread()
                    raise ProviderError(self.NAME, f"HTTP {r.status_code}")
                async for line in r.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except Exception:
                        pass


# ─────────────────────────────────────────────────────────────────
# Ollama Provider (local)
# ─────────────────────────────────────────────────────────────────

class OllamaProvider:
    NAME = "ollama"

    def __init__(self, base_url: str, model: str):
        self._url   = base_url.rstrip("/") + "/api/chat"
        self._model = model

    async def chat(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
    ) -> Tuple[str, int]:
        payload = {
            "model":    self._model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream":   False,
            "options":  {"num_predict": max_tokens},
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=120.0, write=5.0, pool=2.0)
            ) as client:
                r = await client.post(self._url, json=payload)
                r.raise_for_status()
        except httpx.ConnectError as e:
            raise ProviderError(self.NAME, f"Ollama not running: {e}") from e
        except httpx.HTTPStatusError as e:
            raise ProviderError(self.NAME, str(e)) from e

        data  = r.json()
        text  = data.get("message", {}).get("content", "")
        tokens = data.get("eval_count", 0)
        return text, tokens

    async def stream(
        self,
        messages: List[dict],
        system: str,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        payload = {
            "model":    self._model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream":   True,
            "options":  {"num_predict": max_tokens},
        }
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(connect=5.0, read=120.0, write=5.0, pool=2.0)
            ) as client:
                async with client.stream("POST", self._url, json=payload) as r:
                    r.raise_for_status()
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            text = chunk.get("message", {}).get("content", "")
                            if text:
                                yield text
                            if chunk.get("done"):
                                break
                        except Exception:
                            pass
        except httpx.ConnectError as e:
            raise ProviderError(self.NAME, f"Ollama not running: {e}") from e
