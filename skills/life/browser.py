"""
Life Integration — Browser
────────────────────────────
Reads browser history and bookmarks from Chrome / Edge / Firefox.
Allows Javris to know what you've been researching.

Also: open URLs, get page content for summarisation.
"""

from __future__ import annotations

import asyncio
import os
import platform
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

from skills.base import BaseSkill
from core.logger import get_logger

logger = get_logger("javris.skill.browser")

SYSTEM = platform.system()


def _chrome_history_path() -> Path | None:
    """Find Chrome/Edge history database."""
    candidates = []
    if SYSTEM == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", ""))
        candidates = [
            base / "Google/Chrome/User Data/Default/History",
            base / "Microsoft/Edge/User Data/Default/History",
        ]
    elif SYSTEM == "Darwin":
        base = Path.home() / "Library/Application Support"
        candidates = [
            base / "Google/Chrome/Default/History",
            base / "Microsoft Edge/Default/History",
        ]
    else:
        base = Path.home()
        candidates = [
            base / ".config/google-chrome/Default/History",
            base / ".config/chromium/Default/History",
        ]

    for p in candidates:
        if p.exists():
            return p
    return None


class BrowserSkill(BaseSkill):
    name = "browser"
    description = "Read browser history, open URLs, summarise web pages"

    tool_definition = {
        "name": "browser",
        "description": (
            "Interact with the browser. "
            "Actions: recent_history, search_history, open_url, summarise_page."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["recent_history", "search_history", "open_url", "summarise_page"],
                },
                "query": {"type": "string", "description": "Search term for history"},
                "url": {"type": "string", "description": "URL to open or summarise"},
                "limit": {"type": "integer", "default": 10},
                "hours": {"type": "integer", "default": 24, "description": "How far back to look"},
            },
            "required": ["action"],
        },
    }

    async def run(self, action: str, **kwargs) -> Any:
        handlers = {
            "recent_history": self._recent_history,
            "history": self._recent_history,          # alias
            "search_history": self._search_history,
            "open_url": self._open_url,
            "summarise_page": self._summarise_page,
            "summarize_page": self._summarise_page,   # alias
        }
        fn = handlers.get(action)
        if not fn:
            return {"error": f"Unknown action: {action}. Valid: recent_history, search_history, open_url, summarise_page"}
        return await fn(**kwargs)

    async def _recent_history(self, hours: int = 24, limit: int = 20, **_) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._read_history, "", hours, limit)

    async def _search_history(self, query: str = "", limit: int = 10, hours: int = 168, **_) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._read_history, query, hours, limit)

    def _read_history(self, query: str, hours: int, limit: int) -> list[dict]:
        hist_path = _chrome_history_path()
        if not hist_path:
            return [{"error": "Browser history not found. Chrome or Edge must be installed."}]

        # Chrome locks the file — copy it first
        try:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                shutil.copy2(str(hist_path), tmp.name)
                tmp_path = tmp.name

            import time
            cutoff_us = int((time.time() - hours * 3600) * 1_000_000) + 11644473600 * 1_000_000

            conn = sqlite3.connect(tmp_path)
            conn.row_factory = sqlite3.Row

            if query:
                sql = """
                    SELECT url, title, last_visit_time, visit_count
                    FROM urls
                    WHERE (url LIKE ? OR title LIKE ?)
                      AND last_visit_time > ?
                    ORDER BY last_visit_time DESC
                    LIMIT ?
                """
                pattern = f"%{query}%"
                rows = conn.execute(sql, (pattern, pattern, cutoff_us, limit)).fetchall()
            else:
                sql = """
                    SELECT url, title, last_visit_time, visit_count
                    FROM urls
                    WHERE last_visit_time > ?
                    ORDER BY last_visit_time DESC
                    LIMIT ?
                """
                rows = conn.execute(sql, (cutoff_us, limit)).fetchall()

            conn.close()
            os.unlink(tmp_path)

            results = []
            for r in rows:
                # Convert Chrome timestamp to unix
                chrome_ts = r["last_visit_time"]
                unix_ts = (chrome_ts / 1_000_000) - 11644473600
                import time as t
                results.append({
                    "url": r["url"],
                    "title": r["title"] or "(no title)",
                    "visited": t.ctime(unix_ts),
                    "visit_count": r["visit_count"],
                })
            return results
        except Exception as e:
            logger.warning(f"Browser history read failed: {e}")
            return [{"error": str(e)}]

    async def _open_url(self, url: str = "", **_) -> dict:
        if not url:
            return {"error": "url required"}
        try:
            if SYSTEM == "Windows":
                os.startfile(url)
            elif SYSTEM == "Darwin":
                import subprocess
                subprocess.Popen(["open", url])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", url])
            return {"success": True, "url": url}
        except Exception as e:
            return {"error": str(e)}

    async def _summarise_page(self, url: str = "", **_) -> dict:
        if not url:
            return {"error": "url required"}
        try:
            async with httpx.AsyncClient(
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (compatible; Javris/1.0)"},
                follow_redirects=True,
            ) as client:
                r = await client.get(url)
                r.raise_for_status()

            soup = BeautifulSoup(r.text, "lxml")

            # Remove clutter
            for tag in soup(["script", "style", "nav", "footer", "iframe", "ads"]):
                tag.decompose()

            title = soup.title.string.strip() if soup.title else ""
            # Extract main content
            main = soup.find("main") or soup.find("article") or soup.body
            if main:
                text = " ".join(main.get_text(separator=" ").split())[:5000]
            else:
                text = " ".join(soup.get_text(separator=" ").split())[:5000]

            return {
                "url": url,
                "title": title,
                "content": text,
                "length": len(text),
            }
        except Exception as e:
            return {"error": str(e)}
