"""
Notion skill — pages, databases (data sources), blocks via Notion REST API.
Adapted from openclaw/skills/notion SKILL.md — ported to Python + Javris pattern.
API version: 2025-09-03 (latest, databases called "data sources").
"""

from __future__ import annotations

import httpx

from skills.base import BaseSkill
from core.logger import get_logger
from core.config import get_config

logger = get_logger("javris.skill.notion")
cfg = get_config()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"


def _extract_title(obj: dict) -> str:
    """Pull a plain-text title from any Notion page/database object."""
    props = obj.get("properties", {})
    for key in ("Name", "Title", "title"):
        prop = props.get(key, {})
        rich = prop.get("title") or prop.get("rich_text") or []
        if rich:
            return "".join(r.get("plain_text", "") for r in rich)
    # Fallback for database title array at top level
    for t in obj.get("title", []):
        if t.get("plain_text"):
            return t["plain_text"]
    return obj.get("id", "untitled")[:8]


def _blocks_to_text(blocks: list[dict]) -> str:
    """Convert a list of Notion blocks to readable plain text."""
    lines: list[str] = []
    for b in blocks:
        btype = b.get("type", "")
        inner = b.get(btype, {})
        rich = inner.get("rich_text", [])
        text = "".join(r.get("plain_text", "") for r in rich)
        if btype == "heading_1":
            lines.append(f"# {text}")
        elif btype == "heading_2":
            lines.append(f"## {text}")
        elif btype == "heading_3":
            lines.append(f"### {text}")
        elif btype == "bulleted_list_item":
            lines.append(f"- {text}")
        elif btype == "numbered_list_item":
            lines.append(f"1. {text}")
        elif btype == "to_do":
            checked = "x" if inner.get("checked") else " "
            lines.append(f"[{checked}] {text}")
        elif btype == "code":
            lang = inner.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")
        elif text:
            lines.append(text)
    return "\n".join(lines)


class NotionSkill(BaseSkill):
    name = "notion"
    description = "Read and write Notion pages, databases, and blocks"

    tool_definition = {
        "name": "notion",
        "description": (
            "Interact with Notion. Actions: search, get_page, get_page_content, "
            "create_page, update_page, query_database, add_block."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "search", "get_page", "get_page_content",
                        "create_page", "update_page", "query_database", "add_block",
                    ],
                    "description": "Notion operation to perform",
                },
                "page_id": {
                    "type": "string",
                    "description": "Notion page or block UUID",
                },
                "database_id": {
                    "type": "string",
                    "description": "Notion database UUID (for create_page / query_database)",
                },
                "query": {"type": "string", "description": "Search query (for search action)"},
                "title": {"type": "string", "description": "Page title for create_page"},
                "content": {
                    "type": "string",
                    "description": "Paragraph text for create_page or add_block",
                },
                "properties": {
                    "type": "object",
                    "description": "Notion property map for create/update (JSON)",
                },
                "filter": {
                    "type": "object",
                    "description": "Notion filter object for query_database",
                },
            },
            "required": ["action"],
        },
    }

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {cfg.notion_api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    async def run(
        self,
        action: str,
        page_id: str = "",
        database_id: str = "",
        query: str = "",
        title: str = "",
        content: str = "",
        properties: dict | None = None,
        filter: dict | None = None,
    ) -> dict | list | str:
        if not cfg.notion_api_key:
            return "Notion API key not configured — set NOTION_API_KEY in .env"

        logger.info(f"Notion:{action} page={page_id or '-'} db={database_id or '-'}")

        try:
            async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
                match action:
                    case "search":
                        payload: dict = {}
                        if query:
                            payload["query"] = query
                        r = await client.post(f"{NOTION_API}/search", json=payload)
                        r.raise_for_status()
                        results = r.json().get("results", [])
                        return [
                            {
                                "id": p["id"],
                                "title": _extract_title(p),
                                "type": p["object"],
                                "url": p.get("url", ""),
                            }
                            for p in results
                        ]

                    case "get_page":
                        if not page_id:
                            return "page_id required"
                        r = await client.get(f"{NOTION_API}/pages/{page_id}")
                        r.raise_for_status()
                        p = r.json()
                        return {
                            "id": p["id"],
                            "title": _extract_title(p),
                            "url": p.get("url"),
                            "created": (p.get("created_time") or "")[:10],
                            "last_edited": (p.get("last_edited_time") or "")[:10],
                        }

                    case "get_page_content":
                        if not page_id:
                            return "page_id required"
                        r = await client.get(f"{NOTION_API}/blocks/{page_id}/children")
                        r.raise_for_status()
                        blocks = r.json().get("results", [])
                        return _blocks_to_text(blocks) or "(empty page)"

                    case "create_page":
                        if not database_id and not page_id:
                            return "database_id or page_id required as parent"
                        parent = (
                            {"database_id": database_id}
                            if database_id
                            else {"page_id": page_id}
                        )
                        props = properties or {
                            "Name": {"title": [{"text": {"content": title or "Untitled"}}]}
                        }
                        payload = {"parent": parent, "properties": props}
                        if content:
                            payload["children"] = [
                                {
                                    "object": "block",
                                    "type": "paragraph",
                                    "paragraph": {
                                        "rich_text": [{"text": {"content": content}}]
                                    },
                                }
                            ]
                        r = await client.post(f"{NOTION_API}/pages", json=payload)
                        r.raise_for_status()
                        d = r.json()
                        return {"id": d["id"], "url": d.get("url")}

                    case "update_page":
                        if not page_id:
                            return "page_id required"
                        payload = {}
                        if properties:
                            payload["properties"] = properties
                        elif title:
                            payload["properties"] = {
                                "Name": {"title": [{"text": {"content": title}}]}
                            }
                        r = await client.patch(f"{NOTION_API}/pages/{page_id}", json=payload)
                        r.raise_for_status()
                        return {"id": r.json()["id"], "url": r.json().get("url")}

                    case "query_database":
                        if not database_id:
                            return "database_id required"
                        body: dict = {}
                        if filter:
                            body["filter"] = filter
                        r = await client.post(
                            f"{NOTION_API}/databases/{database_id}/query", json=body
                        )
                        r.raise_for_status()
                        return [
                            {"id": p["id"], "title": _extract_title(p), "url": p.get("url", "")}
                            for p in r.json().get("results", [])
                        ]

                    case "add_block":
                        if not page_id or not content:
                            return "page_id and content required"
                        payload = {
                            "children": [
                                {
                                    "object": "block",
                                    "type": "paragraph",
                                    "paragraph": {
                                        "rich_text": [{"text": {"content": content}}]
                                    },
                                }
                            ]
                        }
                        r = await client.patch(
                            f"{NOTION_API}/blocks/{page_id}/children", json=payload
                        )
                        r.raise_for_status()
                        return {"added": True, "results": len(r.json().get("results", []))}

                    case _:
                        return f"Unknown action: {action}"

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return "Notion auth failed — check NOTION_API_KEY in .env"
            if e.response.status_code == 404:
                return "Notion page/database not found — make sure you shared it with your integration"
            return f"Notion API error {e.response.status_code}: {e.response.text[:300]}"
        except Exception as e:
            logger.error(f"Notion skill error: {e}")
            return f"Notion error: {e}"
