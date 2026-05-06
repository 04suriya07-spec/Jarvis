"""Web Search skill – DuckDuckGo (free) + optional SerpAPI."""

from __future__ import annotations

from skills.base import BaseSkill
from core.logger import get_logger
from core.config import get_config

logger = get_logger("javris.skill.web_search")
cfg = get_config()


class WebSearchSkill(BaseSkill):
    name = "web_search"
    description = "Search the web for current information"

    tool_definition = {
        "name": "web_search",
        "description": (
            "Search the internet for up-to-date information. "
            "Use this for news, facts, prices, current events, or anything "
            "that may have changed after your training data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-10)",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    }

    async def run(self, query: str, max_results: int = 5) -> list[dict]:
        logger.info(f"Web search: {query!r}")
        results = await self._ddg_search(query, max_results)
        if not results and cfg.serpapi_key:
            results = await self._serp_search(query, max_results)
        return results

    async def _ddg_search(self, query: str, n: int) -> list[dict]:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
            import asyncio

            loop = asyncio.get_event_loop()

            def _search():
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=n))

            results = await loop.run_in_executor(None, _search)
            return [
                {
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                }
                for r in results
            ]
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")
            return []

    async def _serp_search(self, query: str, n: int) -> list[dict]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    "https://serpapi.com/search",
                    params={"q": query, "num": n, "api_key": cfg.serpapi_key},
                )
                r.raise_for_status()
                data = r.json()
                return [
                    {
                        "title": item.get("title", ""),
                        "url": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    }
                    for item in data.get("organic_results", [])[:n]
                ]
        except Exception as e:
            logger.warning(f"SerpAPI search failed: {e}")
            return []
