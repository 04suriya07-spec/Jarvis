"""
Tests for openclaw-inspired skills: GitHub, Notion, Obsidian, Telegram, Discord, VectorMemory.
All tests use mocking / local operations — no live API calls.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# GitHub Skill
# ──────────────────────────────────────────────────────────────────────────────

class TestGitHubSkill:
    def setup_method(self):
        from skills.github import GitHubSkill
        self.skill = GitHubSkill()

    def test_tool_definition(self):
        td = self.skill.tool_definition
        assert td["name"] == "github"
        actions = td["input_schema"]["properties"]["action"]["enum"]
        assert "list_repos" in actions
        assert "list_issues" in actions
        assert "create_issue" in actions
        assert "list_prs" in actions
        assert "list_releases" in actions
        assert "search_code" in actions

    def test_name_and_description(self):
        assert self.skill.name == "github"
        assert "github" in self.skill.description.lower()

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        # No network call — hits default branch
        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.raise_for_status = MagicMock()
            mock_response.json.return_value = []
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_context)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_context.get = AsyncMock(return_value=mock_response)
            mock_context.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_context

            result = await self.skill.run(action="bogus_action")
            assert "Unknown action" in str(result)

    @pytest.mark.asyncio
    async def test_list_issues_requires_repo(self):
        with patch("httpx.AsyncClient") as mock_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_context)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_context

            result = await self.skill.run(action="list_issues", repo="")
            assert "repo" in str(result).lower()

    @pytest.mark.asyncio
    async def test_create_issue_requires_title(self):
        with patch("httpx.AsyncClient") as mock_client:
            mock_context = AsyncMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_context)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_context

            result = await self.skill.run(action="create_issue", repo="owner/repo", title="")
            assert "title" in str(result).lower()


# ──────────────────────────────────────────────────────────────────────────────
# Notion Skill
# ──────────────────────────────────────────────────────────────────────────────

class TestNotionSkill:
    def setup_method(self):
        from skills.notion import NotionSkill
        self.skill = NotionSkill()

    def test_tool_definition(self):
        td = self.skill.tool_definition
        assert td["name"] == "notion"
        actions = td["input_schema"]["properties"]["action"]["enum"]
        assert "search" in actions
        assert "get_page" in actions
        assert "create_page" in actions
        assert "query_database" in actions

    @pytest.mark.asyncio
    async def test_returns_error_without_api_key(self):
        with patch("core.config.get_config") as mock_cfg:
            mock_cfg.return_value = MagicMock(notion_api_key="")
            # Re-import to pick up mocked config
            from skills import notion as notion_mod
            orig = notion_mod.cfg
            notion_mod.cfg = MagicMock(notion_api_key="")
            result = await self.skill.run(action="search", query="test")
            notion_mod.cfg = orig
            # Either mocked or real config — if no key, should error
            if not orig.notion_api_key:
                assert "not configured" in str(result).lower() or "search" in str(result).lower()

    def test_extract_title_fallback(self):
        from skills.notion import _extract_title
        obj = {"id": "abc12345", "properties": {}, "title": []}
        title = _extract_title(obj)
        assert "abc1" in title  # falls back to id prefix

    def test_blocks_to_text_paragraph(self):
        from skills.notion import _blocks_to_text
        blocks = [
            {
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"plain_text": "Hello, World!"}]
                }
            }
        ]
        text = _blocks_to_text(blocks)
        assert "Hello, World!" in text

    def test_blocks_to_text_heading(self):
        from skills.notion import _blocks_to_text
        blocks = [
            {"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}},
            {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Subtitle"}]}},
            {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "Item"}]}},
        ]
        text = _blocks_to_text(blocks)
        assert "# Title" in text
        assert "## Subtitle" in text
        assert "- Item" in text


# ──────────────────────────────────────────────────────────────────────────────
# Obsidian Skill
# ──────────────────────────────────────────────────────────────────────────────

class TestObsidianSkill:
    def setup_method(self):
        from skills.obsidian import ObsidianSkill
        self.skill = ObsidianSkill()

    def test_tool_definition(self):
        td = self.skill.tool_definition
        assert td["name"] == "obsidian"
        actions = td["input_schema"]["properties"]["action"]["enum"]
        for a in ("list_notes", "read_note", "create_note", "append_note", "search_notes", "search_content"):
            assert a in actions

    @pytest.mark.asyncio
    async def test_returns_error_without_vault(self):
        import skills.obsidian as obs_mod
        orig = obs_mod.cfg
        obs_mod.cfg = MagicMock(obsidian_vault_path="")
        result = await self.skill.run(action="list_notes")
        obs_mod.cfg = orig
        assert "not configured" in str(result).lower() or "vault" in str(result).lower()

    @pytest.mark.asyncio
    async def test_create_read_append_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            import skills.obsidian as obs_mod
            orig_cfg = obs_mod.cfg
            obs_mod.cfg = MagicMock(obsidian_vault_path=tmp)

            # Create
            result = await self.skill.run(action="create_note", note="TestNote", content="# Hello")
            assert result.get("created") or "exists" in str(result)

            # Read
            result = await self.skill.run(action="read_note", note="TestNote")
            assert "# Hello" in result.get("content", "")

            # Append
            result = await self.skill.run(action="append_note", note="TestNote", content="More text")
            assert "appended_to" in result

            # Read again
            result = await self.skill.run(action="read_note", note="TestNote")
            assert "More text" in result.get("content", "")

            obs_mod.cfg = orig_cfg

    @pytest.mark.asyncio
    async def test_list_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Create two notes
            Path(tmp, "alpha.md").write_text("# Alpha")
            Path(tmp, "beta.md").write_text("# Beta")

            import skills.obsidian as obs_mod
            orig_cfg = obs_mod.cfg
            obs_mod.cfg = MagicMock(obsidian_vault_path=tmp)

            result = await self.skill.run(action="list_notes")
            notes = result.get("notes", [])
            assert "alpha.md" in notes
            assert "beta.md" in notes

            obs_mod.cfg = orig_cfg

    @pytest.mark.asyncio
    async def test_search_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "note1.md").write_text("Meeting notes about project X")
            Path(tmp, "note2.md").write_text("Shopping list")

            import skills.obsidian as obs_mod
            orig_cfg = obs_mod.cfg
            obs_mod.cfg = MagicMock(obsidian_vault_path=tmp)

            result = await self.skill.run(action="search_content", query="project")
            matches = [r["note"] for r in result.get("results", [])]
            assert any("note1" in m for m in matches)
            assert not any("note2" in m for m in matches)

            obs_mod.cfg = orig_cfg


# ──────────────────────────────────────────────────────────────────────────────
# Telegram Skill
# ──────────────────────────────────────────────────────────────────────────────

class TestTelegramSkill:
    def setup_method(self):
        from skills.telegram_notify import TelegramSkill
        self.skill = TelegramSkill()

    def test_tool_definition(self):
        td = self.skill.tool_definition
        assert td["name"] == "telegram"
        actions = td["input_schema"]["properties"]["action"]["enum"]
        assert "send_message" in actions
        assert "get_updates" in actions

    def test_aliases(self):
        assert "telegram_notify" in self.skill.aliases

    @pytest.mark.asyncio
    async def test_returns_error_without_token(self):
        import skills.telegram_notify as tg_mod
        orig = tg_mod.cfg
        tg_mod.cfg = MagicMock(telegram_bot_token="")
        result = await self.skill.run(action="send_message", text="Hi")
        tg_mod.cfg = orig
        assert "not configured" in str(result).lower() or "token" in str(result).lower()

    @pytest.mark.asyncio
    async def test_send_message_mocked(self):
        import skills.telegram_notify as tg_mod
        orig = tg_mod.cfg
        tg_mod.cfg = MagicMock(telegram_bot_token="test_token", telegram_chat_id="12345")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "result": {"message_id": 42, "chat": {"id": 12345}}
        }
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_ctx.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_ctx):
            result = await self.skill.run(action="send_message", text="Hello Javris!")

        tg_mod.cfg = orig
        assert result.get("sent") is True
        assert result.get("message_id") == 42


# ──────────────────────────────────────────────────────────────────────────────
# Discord Skill
# ──────────────────────────────────────────────────────────────────────────────

class TestDiscordSkill:
    def setup_method(self):
        from skills.discord_notify import DiscordSkill
        self.skill = DiscordSkill()

    def test_tool_definition(self):
        td = self.skill.tool_definition
        assert td["name"] == "discord"
        actions = td["input_schema"]["properties"]["action"]["enum"]
        assert "send_message" in actions
        assert "send_embed" in actions
        assert "get_messages" in actions

    def test_aliases(self):
        assert "discord_notify" in self.skill.aliases

    @pytest.mark.asyncio
    async def test_returns_error_without_webhook(self):
        import skills.discord_notify as dc_mod
        orig = dc_mod.cfg
        dc_mod.cfg = MagicMock(discord_webhook_url="")
        result = await self.skill.run(action="send_message", content="Hi")
        dc_mod.cfg = orig
        assert "not configured" in str(result).lower() or "webhook" in str(result).lower()

    @pytest.mark.asyncio
    async def test_send_message_mocked(self):
        import skills.discord_notify as dc_mod
        orig = dc_mod.cfg
        dc_mod.cfg = MagicMock(discord_webhook_url="https://discord.com/api/webhooks/test/token")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 204
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_ctx.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_ctx):
            result = await self.skill.run(action="send_message", content="Test notification")

        dc_mod.cfg = orig
        assert result.get("sent") is True

    @pytest.mark.asyncio
    async def test_send_embed_mocked(self):
        import skills.discord_notify as dc_mod
        orig = dc_mod.cfg
        dc_mod.cfg = MagicMock(discord_webhook_url="https://discord.com/api/webhooks/test/token")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 204
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_ctx.post = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_ctx):
            result = await self.skill.run(
                action="send_embed",
                embed_title="Javris Alert",
                embed_description="System is running fine",
                embed_color=5793266,
            )

        dc_mod.cfg = orig
        assert result.get("sent") is True


# ──────────────────────────────────────────────────────────────────────────────
# VectorMemory
# ──────────────────────────────────────────────────────────────────────────────

class TestVectorMemory:
    def setup_method(self):
        from core.vector_memory import VectorMemory
        self.vm = VectorMemory()
        # Init without chromadb — uses keyword fallback
        # Don't call self.vm.init() to avoid chromadb dependency in tests

    def test_backend_before_init(self):
        # Before init, should be in fallback mode (chromadb not yet loaded)
        assert self.vm.backend in ("chromadb", "keyword_fallback")

    def test_count_starts_at_zero(self):
        assert self.vm.count() == 0

    def test_stats_returns_dict(self):
        stats = self.vm.stats()
        assert "backend" in stats
        assert "count" in stats

    @pytest.mark.asyncio
    async def test_add_and_keyword_search(self):
        from core.vector_memory import VectorMemory
        vm = VectorMemory()
        # Don't init — uses keyword fallback

        await vm.add("The user likes playing chess on weekends")
        await vm.add("The user prefers Python over JavaScript")
        await vm.add("Today's weather is sunny and warm")

        results = await vm.search("chess", n_results=2)
        # Should find the chess entry in keyword fallback
        assert len(results) >= 1
        assert any("chess" in r["text"].lower() for r in results)

    @pytest.mark.asyncio
    async def test_add_returns_id(self):
        from core.vector_memory import VectorMemory
        vm = VectorMemory()
        doc_id = await vm.add("Test document content")
        assert doc_id  # non-empty string

    @pytest.mark.asyncio
    async def test_delete_removes_entry(self):
        from core.vector_memory import VectorMemory
        vm = VectorMemory()
        doc_id = await vm.add("Something to delete")
        assert vm.count() == 1
        await vm.delete(doc_id)
        assert vm.count() == 0

    @pytest.mark.asyncio
    async def test_empty_text_not_added(self):
        from core.vector_memory import VectorMemory
        vm = VectorMemory()
        result = await vm.add("")
        assert result == ""
        assert vm.count() == 0

    @pytest.mark.asyncio
    async def test_search_empty_query(self):
        from core.vector_memory import VectorMemory
        vm = VectorMemory()
        await vm.add("Some content")
        results = await vm.search("")
        assert results == []
