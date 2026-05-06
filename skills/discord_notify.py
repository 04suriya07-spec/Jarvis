"""
Discord notification skill — send messages and embeds via Discord webhook or bot.
Inspired by openclaw/extensions/discord — ported to Python + Javris pattern.
Config: DISCORD_WEBHOOK_URL (webhook) and optional DISCORD_BOT_TOKEN + DISCORD_CHANNEL_ID (bot API).
"""

from __future__ import annotations

import httpx

from skills.base import BaseSkill
from core.logger import get_logger
from core.config import get_config

logger = get_logger("javris.skill.discord")
cfg = get_config()

DISCORD_API = "https://discord.com/api/v10"


class DiscordSkill(BaseSkill):
    name = "discord"
    description = "Send messages and embeds to Discord via webhook or bot"
    aliases = ["discord_notify", "notify_discord"]

    tool_definition = {
        "name": "discord",
        "description": (
            "Send Discord messages/embeds, or fetch channel messages via bot. "
            "Actions: send_message, send_embed, get_messages."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["send_message", "send_embed", "get_messages"],
                    "description": "Discord action",
                },
                "content": {
                    "type": "string",
                    "description": "Plain text message content",
                },
                "username": {
                    "type": "string",
                    "description": "Override display name for webhook message",
                },
                "embed_title": {
                    "type": "string",
                    "description": "Embed title (for send_embed)",
                },
                "embed_description": {
                    "type": "string",
                    "description": "Embed body text (for send_embed, supports Markdown)",
                },
                "embed_color": {
                    "type": "integer",
                    "description": "Embed sidebar colour as decimal integer (e.g. 5793266 = #5865F2)",
                },
                "embed_url": {
                    "type": "string",
                    "description": "URL to hyperlink on embed title",
                },
                "embed_fields": {
                    "type": "array",
                    "description": "List of {name, value, inline} field objects",
                    "items": {"type": "object"},
                },
                "channel_id": {
                    "type": "string",
                    "description": "Channel ID for get_messages (requires DISCORD_BOT_TOKEN)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of messages to fetch (1-100)",
                    "default": 10,
                },
            },
            "required": ["action"],
        },
    }

    async def run(
        self,
        action: str,
        content: str = "",
        username: str = "Javris",
        embed_title: str = "",
        embed_description: str = "",
        embed_color: int = 5793266,  # Discord blurple
        embed_url: str = "",
        embed_fields: list | None = None,
        channel_id: str = "",
        limit: int = 10,
    ) -> dict | list | str:
        logger.info(f"Discord:{action}")

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                match action:
                    case "send_message":
                        if not cfg.discord_webhook_url:
                            return "Discord webhook not configured — set DISCORD_WEBHOOK_URL in .env"
                        if not content:
                            return "content required"
                        payload: dict = {"content": content, "username": username}
                        r = await client.post(cfg.discord_webhook_url, json=payload)
                        r.raise_for_status()
                        return {"sent": True, "status": r.status_code}

                    case "send_embed":
                        if not cfg.discord_webhook_url:
                            return "Discord webhook not configured — set DISCORD_WEBHOOK_URL in .env"
                        embed: dict = {"color": embed_color}
                        if embed_title:
                            embed["title"] = embed_title
                        if embed_description:
                            embed["description"] = embed_description
                        if embed_url:
                            embed["url"] = embed_url
                        if embed_fields:
                            embed["fields"] = embed_fields
                        payload = {
                            "username": username,
                            "embeds": [embed],
                        }
                        if content:
                            payload["content"] = content
                        r = await client.post(cfg.discord_webhook_url, json=payload)
                        r.raise_for_status()
                        return {"sent": True, "status": r.status_code}

                    case "get_messages":
                        bot_token = getattr(cfg, "discord_bot_token", "")
                        cid = channel_id or getattr(cfg, "discord_channel_id", "")
                        if not bot_token:
                            return "DISCORD_BOT_TOKEN required for get_messages"
                        if not cid:
                            return "channel_id required"
                        r = await client.get(
                            f"{DISCORD_API}/channels/{cid}/messages",
                            params={"limit": min(limit, 100)},
                            headers={"Authorization": f"Bot {bot_token}"},
                        )
                        r.raise_for_status()
                        msgs = r.json()
                        return [
                            {
                                "id": m["id"],
                                "author": m["author"]["username"],
                                "content": m["content"][:200],
                                "timestamp": m["timestamp"][:19],
                            }
                            for m in msgs
                        ]

                    case _:
                        return f"Unknown action: {action}"

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return "Discord auth failed — check DISCORD_WEBHOOK_URL / DISCORD_BOT_TOKEN"
            if e.response.status_code == 404:
                return "Discord channel or webhook not found"
            return f"Discord API error {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            logger.error(f"Discord skill error: {e}")
            return f"Discord error: {e}"
