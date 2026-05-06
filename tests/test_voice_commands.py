"""
Tests for core/voice_commands.py — parse_command + execute_command
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.voice_commands import parse_command, VoiceCommand


# ── parse_command tests ───────────────────────────────────────────

class TestParseCommand:

    def test_weather_command(self):
        cmd = parse_command("what's the weather in London")
        assert cmd.intent == "weather"
        assert cmd.action == "get_weather"
        # location is lowercased by the regex
        assert cmd.params.get("location", "").lower() == "london"
        assert not cmd.is_ui_command

    def test_weather_command_no_location(self):
        cmd = parse_command("show the weather")
        assert cmd.intent == "weather"

    def test_news_command(self):
        # Use a phrase that clearly matches the news pattern
        cmd = parse_command("get the latest news about crypto")
        assert cmd.intent == "news"
        assert cmd.params.get("topic") == "crypto"

    def test_news_command_no_topic(self):
        cmd = parse_command("what's the news")
        assert cmd.intent == "news"

    def test_mode_switch_work(self):
        cmd = parse_command("switch to work mode")
        assert cmd.intent == "switch_mode"
        assert "work" in cmd.params.get("mode", "")

    def test_mode_switch_trading(self):
        cmd = parse_command("activate trading mode")
        assert cmd.intent == "switch_mode"

    def test_mode_switch_focus(self):
        cmd = parse_command("enable focus mode")
        assert cmd.intent == "switch_mode"

    def test_create_note(self):
        cmd = parse_command("note: meeting with Alex at 3pm")
        assert cmd.intent == "create_note"
        assert "meeting" in cmd.params.get("content", "")

    def test_create_task(self):
        cmd = parse_command("add task: review pull request")
        assert cmd.intent == "create_task"
        assert "review" in cmd.params.get("title", "")

    def test_web_search(self):
        cmd = parse_command("search for quantum computing")
        assert cmd.intent == "web_search"
        assert "quantum" in cmd.params.get("query", "")

    def test_system_info(self):
        cmd = parse_command("show system status")
        assert cmd.intent == "system_info"

    def test_screenshot(self):
        cmd = parse_command("take a screenshot")
        assert cmd.intent == "screenshot"

    def test_research(self):
        # "deep dive" phrase triggers research intent
        cmd = parse_command("deep dive into climate change")
        assert cmd.intent == "research"
        assert "climate" in cmd.params.get("topic", "")

    def test_reminder(self):
        cmd = parse_command("remind me to call mum at 5pm")
        assert cmd.intent == "reminder"

    def test_fallback_to_chat(self):
        cmd = parse_command("how do black holes form?")
        assert cmd.intent == "chat"
        assert cmd.action == "chat"

    # UI commands
    def test_ui_open_chat(self):
        cmd = parse_command("open chat")
        assert cmd.is_ui_command
        assert cmd.params.get("panel") == "chat"

    def test_ui_open_tasks(self):
        cmd = parse_command("open tasks")
        assert cmd.is_ui_command

    def test_ui_minimize_panels(self):
        cmd = parse_command("minimize all panels")
        assert cmd.is_ui_command

    def test_confidence_is_reasonable(self):
        cmd = parse_command("what's the weather in Paris")
        assert 0.0 < cmd.confidence <= 1.0

    def test_raw_text_preserved(self):
        original = "Search for machine learning tutorials"
        cmd = parse_command(original)
        assert cmd.raw_text == original


# ── execute_command tests ─────────────────────────────────────────

class TestExecuteCommand:

    @pytest.mark.asyncio
    async def test_chat_fallback(self):
        from core.voice_commands import execute_command
        assistant = AsyncMock()
        assistant.chat.return_value = "Hello!"
        cmd = VoiceCommand(intent="chat", action="chat",
                           params={"message": "hi"}, confidence=0.7,
                           raw_text="hi", is_ui_command=False)
        result = await execute_command(cmd, assistant)
        assert result["action_taken"] == "chat"
        assert "Hello!" in result["response"]

    @pytest.mark.asyncio
    async def test_switch_mode_calls_manager(self):
        from core.voice_commands import execute_command
        assistant = MagicMock()
        cmd = VoiceCommand(intent="switch_mode", action="switch_mode",
                           params={"mode": "trading"}, confidence=0.9,
                           raw_text="switch to trading mode", is_ui_command=False)

        with patch("core.modes.ModeManager") as MockMgr:
            instance = AsyncMock()
            instance.match_from_voice.return_value = "trading"
            instance.switch.return_value = {
                "switched_to": "trading",
                "name": "Trading Mode",
                "panels": ["news", "research"],
                "layout": "tile",
            }
            MockMgr.return_value = instance
            result = await execute_command(cmd, assistant)

        assert result["action_taken"] == "mode_switched"

    @pytest.mark.asyncio
    async def test_system_info_skill(self):
        from core.voice_commands import execute_command
        skill = AsyncMock()
        skill.run.return_value = {"cpu_percent": 42, "ram_percent": 60, "disk_percent": 55}
        assistant = MagicMock()
        assistant._skill_registry = {"system_control": skill}

        cmd = VoiceCommand(intent="system_info", action="system_info",
                           params={}, confidence=0.9,
                           raw_text="system status", is_ui_command=False)
        result = await execute_command(cmd, assistant)
        assert result["action_taken"] == "system_info"
        assert "42" in result["response"]

    @pytest.mark.asyncio
    async def test_notes_create(self):
        from core.voice_commands import execute_command
        skill = AsyncMock()
        skill.run.return_value = {"success": True, "note_id": "abc123"}
        assistant = MagicMock()
        assistant._skill_registry = {"notes": skill}

        cmd = VoiceCommand(intent="create_note", action="notes_create",
                           params={"content": "buy milk"}, confidence=0.9,
                           raw_text="note buy milk", is_ui_command=False)
        result = await execute_command(cmd, assistant)
        assert result["action_taken"] == "note_created"
        skill.run.assert_called_once_with(action="create",
                                          title="buy milk"[:40],
                                          content="buy milk")
