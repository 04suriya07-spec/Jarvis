"""
Telegram notification skill — send messages, photos, and receive updates
via the Telegram Bot API.
Inspired by openclaw/extensions/telegram — ported to Python + Javris pattern.
Config: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID in .env
"""

from __future__ import annotations

import httpx

from skills.base import BaseSkill
from core.logger import get_logger
from core.config import get_config

logger = get_logger("javris.skill.telegram")
cfg = get_config()

TG_API = "https://api.telegram.org"


def _api_url(method: str) -> str:
    return f"{TG_API}/bot{cfg.telegram_bot_token}/{method}"


class TelegramSkill(BaseSkill):
    name = "telegram"
    description = "Send messages and notifications via Telegram bot"
    aliases = ["telegram_notify", "notify_telegram"]

    tool_definition = {
        "name": "telegram",
        "description": (
            "Send Telegram messages / notifications or get recent messages from the bot. "
            "Actions: send_message, send_photo, get_updates, get_me."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["send_message", "send_photo", "get_updates", "get_me"],
                    "description": "Telegram action",
                },
                "text": {
                    "type": "string",
                    "description": "Message text (supports Markdown)",
                },
                "photo_url": {
                    "type": "string",
                    "description": "Public URL of a photo to send",
                },
                "caption": {
                    "type": "string",
                    "description": "Caption for a photo",
                },
                "chat_id": {
                    "type": "string",
                    "description": "Telegram chat ID (defaults to TELEGRAM_CHAT_ID from config)",
                },
                "parse_mode": {
                    "type": "string",
                    "enum": ["Markdown", "HTML", "MarkdownV2"],
                    "description": "Message parse mode",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max updates to fetch (1-100)",
                    "default": 10,
                },
            },
            "required": ["action"],
        },
    }

    def _resolve_chat(self, chat_id: str) -> str:
        return chat_id or cfg.telegram_chat_id

    async def run(
        self,
        action: str,
        text: str = "",
        photo_url: str = "",
        caption: str = "",
        chat_id: str = "",
        parse_mode: str = "Markdown",
        limit: int = 10,
    ) -> dict | list | str:
        if not cfg.telegram_bot_token:
            return "Telegram bot token not configured — set TELEGRAM_BOT_TOKEN in .env"

        logger.info(f"Telegram:{action}")

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                match action:
                    case "get_me":
                        r = await client.get(_api_url("getMe"))
                        r.raise_for_status()
                        bot = r.json().get("result", {})
                        return {
                            "username": bot.get("username"),
                            "name": bot.get("first_name"),
                            "id": bot.get("id"),
                        }

                    case "send_message":
                        cid = self._resolve_chat(chat_id)
                        if not cid:
                            return "chat_id required — set TELEGRAM_CHAT_ID in .env or pass chat_id"
                        if not text:
                            return "text required"
                        payload: dict = {
                            "chat_id": cid,
                            "text": text,
                            "parse_mode": parse_mode,
                        }
                        r = await client.post(_api_url("sendMessage"), json=payload)
                        r.raise_for_status()
                        d = r.json().get("result", {})
                        return {
                            "sent": True,
                            "message_id": d.get("message_id"),
                            "chat": d.get("chat", {}).get("id"),
                        }

                    case "send_photo":
                        cid = self._resolve_chat(chat_id)
                        if not cid:
                            return "chat_id required"
                        if not photo_url:
                            return "photo_url required"
                        payload = {
                            "chat_id": cid,
                            "photo": photo_url,
                        }
                        if caption:
                            payload["caption"] = caption
                            payload["parse_mode"] = parse_mode
                        r = await client.post(_api_url("sendPhoto"), json=payload)
                        r.raise_for_status()
                        d = r.json().get("result", {})
                        return {"sent": True, "message_id": d.get("message_id")}

                    case "get_updates":
                        r = await client.get(
                            _api_url("getUpdates"),
                            params={"limit": min(limit, 100), "timeout": 0},
                        )
                        r.raise_for_status()
                        updates = r.json().get("result", [])
                        return [
                            {
                                "update_id": u.get("update_id"),
                                "from": (u.get("message", {}).get("from") or {}).get("username"),
                                "text": (u.get("message", {}) or {}).get("text", ""),
                                "date": u.get("message", {}).get("date"),
                            }
                            for u in updates
                        ]

                    case _:
                        return f"Unknown action: {action}"

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return "Telegram bot token invalid — check TELEGRAM_BOT_TOKEN"
            return f"Telegram API error {e.response.status_code}: {e.response.text[:200]}"
        except Exception as e:
            logger.error(f"Telegram skill error: {e}")
            return f"Telegram error: {e}"
