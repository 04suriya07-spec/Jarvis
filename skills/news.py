"""
Javris News Skill — Multi-Source Intelligence Feed
─────────────────────────────────────────────────
Priority waterfall:
  1. GNews      (keyed, rich metadata)
  2. MarketAux  (finance / market focus)
  3. NewsData   (keyed backup)
  4. Spaceflight News (tech/science, no key)
  5. Inshorts   (quick reads, no key)
  6. DuckDuckGo (final offline-capable fallback)

All results normalised to the same dict structure.
5-minute TTL cache + 3 retries on every source.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from skills.base import BaseSkill
from core.config import get_config
from core.logger import get_logger
from core.retry import resilient, with_retry, cached

logger = get_logger("javris.skill.news")
cfg = get_config()


import re as _re

def _sanitize(text: str) -> str:
    """Remove zero-width spaces, control characters and other problematic Unicode."""
    if not text:
        return ""
    # Strip zero-width and invisible chars
    text = _re.sub(r'[\u200b\u200c\u200d\ufeff\u00ad]', '', text)
    return text.strip()


def _norm(article: dict, source_label: str) -> dict:
    """Normalise any news API response to a common structure."""
    return {
        "title":     _sanitize(article.get("title") or article.get("heading") or ""),
        "source":    article.get("source", {}).get("name", "") if isinstance(article.get("source"), dict)
                     else str(article.get("source", source_label)),
        "published": (article.get("publishedAt") or article.get("published_date") or
                      article.get("date") or "")[:10],
        "url":       article.get("url") or article.get("readMoreUrl") or "",
        "summary":   _sanitize((article.get("description") or article.get("content") or
                      article.get("body") or ""))[:300],
        "image":     article.get("image") or article.get("urlToImage") or article.get("imageUrl") or "",
        "_source":   source_label,
    }


class NewsSkill(BaseSkill):
    name = "get_news"
    description = "Fetch top news headlines from multiple live sources"

    tool_definition = {
        "name": "get_news",
        "description": (
            "Fetch top news headlines by topic, category, or country. "
            "Returns real-time articles from GNews, MarketAux, NewsData, "
            "Spaceflight, and Inshorts as fallbacks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic or keyword to search for (optional)",
                },
                "category": {
                    "type": "string",
                    "description": "Category: general | business | technology | sports | science | health | entertainment",
                    "default": "general",
                },
                "country": {
                    "type": "string",
                    "description": "2-letter country code (e.g. 'in', 'us', 'gb')",
                    "default": "in",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of articles (1-20)",
                    "default": 5,
                },
                "finance": {
                    "type": "boolean",
                    "description": "If true, prefer financial/market news sources",
                    "default": False,
                },
            },
            "required": [],
        },
    }

    @resilient(ttl=300, max_retries=3, base_delay=1.0, max_delay=10.0)
    async def run(
        self,
        topic: str = "",
        category: str = "general",
        country: str = "in",
        count: int = 5,
        finance: bool = False,
        **_,
    ) -> list[dict]:
        articles: list[dict] = []

        # ── 1. GNews (primary) ────────────────────────────────
        if cfg.gnews_api_key and not articles:
            articles = await self._gnews(topic, category, country, count)

        # ── 2. MarketAux (finance focused) ───────────────────
        if cfg.marketaux_api_key and (finance or topic.lower() in ("finance", "market", "stocks", "trading")) and len(articles) < count:
            articles += await self._marketaux(topic, count - len(articles))

        # ── 3. NewsData.io (backup) ──────────────────────────
        if cfg.newsdata_api_key and len(articles) < count:
            articles += await self._newsdata(topic, country, count - len(articles))

        # ── 4. Spaceflight (tech/science, no key) ────────────
        if len(articles) < count and category in ("", "general", "technology", "science"):
            articles += await self._spaceflight(count - len(articles))

        # ── 5. Inshorts (no key) ─────────────────────────────
        if len(articles) < count:
            articles += await self._inshorts(category, count - len(articles))

        # ── 6. DuckDuckGo final fallback ─────────────────────
        if not articles:
            articles = await self._ddg_news(topic or "top news", count)

        # Deduplicate by URL and trim
        seen: set[str] = set()
        result: list[dict] = []
        for a in articles:
            url = a.get("url", "")
            if url and url not in seen:
                seen.add(url)
                result.append(a)
        return result[:count]

    # ── Source implementations ───────────────────────────────

    @with_retry(max_retries=2, base_delay=0.5)
    async def _gnews(self, topic: str, category: str, country: str, count: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if topic:
                    url = f"{cfg.gnews_base_url}/search"
                    params = {"q": topic, "lang": "en", "country": country,
                              "max": count, "apikey": cfg.gnews_api_key}
                else:
                    url = f"{cfg.gnews_base_url}/top-headlines"
                    params = {"category": category, "lang": "en", "country": country,
                              "max": count, "apikey": cfg.gnews_api_key}
                r = await client.get(url, params=params)
                if r.status_code == 200:
                    return [_norm(a, "GNews") for a in r.json().get("articles", [])]
        except Exception as e:
            logger.debug(f"GNews failed: {e}")
        return []

    @with_retry(max_retries=2, base_delay=0.5)
    async def _marketaux(self, topic: str, count: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                params = {
                    "api_token": cfg.marketaux_api_key,
                    "language": "en",
                    "limit": count,
                }
                if topic:
                    params["search"] = topic
                r = await client.get(f"{cfg.marketaux_base_url}/news/all", params=params)
                if r.status_code == 200:
                    return [_norm(a, "MarketAux") for a in r.json().get("data", [])]
        except Exception as e:
            logger.debug(f"MarketAux failed: {e}")
        return []

    @with_retry(max_retries=2, base_delay=0.5)
    async def _newsdata(self, topic: str, country: str, count: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                params = {
                    "apikey": cfg.newsdata_api_key,
                    "country": country,
                    "language": "en",
                    "size": count,
                }
                if topic:
                    params["q"] = topic
                r = await client.get(f"{cfg.newsdata_base_url}/news", params=params)
                if r.status_code == 200:
                    return [_norm(a, "NewsData") for a in r.json().get("results", [])]
        except Exception as e:
            logger.debug(f"NewsData failed: {e}")
        return []

    @with_retry(max_retries=2, base_delay=0.5)
    async def _spaceflight(self, count: int) -> list[dict]:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(f"{cfg.spaceflight_base_url}/articles/", params={"limit": count})
                if r.status_code == 200:
                    return [_norm(a, "SpaceflightNews") for a in r.json().get("results", [])]
        except Exception as e:
            logger.debug(f"Spaceflight failed: {e}")
        return []

    @with_retry(max_retries=2, base_delay=0.5)
    async def _inshorts(self, category: str, count: int) -> list[dict]:
        try:
            cat_map = {"technology": "technology", "business": "business",
                       "sports": "sports", "general": "all", "": "all"}
            cat = cat_map.get(category, "all")
            async with httpx.AsyncClient(timeout=8) as client:
                r = await client.get(f"{cfg.inshorts_base_url}/news", params={"category": cat})
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    return [_norm(a, "Inshorts") for a in data[:count]]
        except Exception as e:
            logger.debug(f"Inshorts failed: {e}")
        return []

    @with_retry(max_retries=2, base_delay=0.5)
    async def _ddg_news(self, query: str, n: int) -> list[dict]:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS

            loop = asyncio.get_event_loop()

            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.news(query, max_results=n))

            results = await loop.run_in_executor(None, _search)
            return [_norm(r, "DuckDuckGo") for r in results]
        except Exception as e:
            logger.warning(f"DDG news fallback failed: {e}")
            return []
