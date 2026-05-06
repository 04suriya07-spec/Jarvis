"""
Tests for core/modes.py — ModeManager
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def mode_manager():
    from core.modes import ModeManager
    with patch("core.modes.DATA_PATH") as mp:
        mp.exists.return_value = False  # don't load from disk
        mgr = ModeManager(autonomy=None)
    return mgr


@pytest.fixture
def mode_manager_with_autonomy():
    from core.modes import ModeManager
    autonomy = AsyncMock()
    with patch("core.modes.DATA_PATH") as mp:
        mp.exists.return_value = False
        mgr = ModeManager(autonomy=autonomy)
    mgr._autonomy = autonomy
    return mgr, autonomy


# ── Tests ─────────────────────────────────────────────────────────

def test_default_mode_is_work(mode_manager):
    assert mode_manager.current_id == "work"


def test_switch_valid_mode(mode_manager):
    result = asyncio.run(mode_manager.switch("trading"))
    assert result.get("switched_to") == "trading"
    assert mode_manager.current_id == "trading"


def test_switch_invalid_mode(mode_manager):
    result = asyncio.run(mode_manager.switch("unknown_mode_xyz"))
    assert "error" in result
    assert "available" in result


def test_list_modes_returns_all_six(mode_manager):
    modes = mode_manager.list_modes()
    ids = [m["id"] for m in modes]
    for expected in ["work", "trading", "dev", "focus", "night", "research"]:
        assert expected in ids, f"Missing mode: {expected}"


def test_switch_sets_correct_panels(mode_manager):
    result = asyncio.run(mode_manager.switch("trading"))
    assert "news" in result["panels"]

    result = asyncio.run(mode_manager.switch("focus"))
    assert result["panels"] == ["chat"]


def test_switch_triggers_autonomy_broadcast(mode_manager_with_autonomy):
    mgr, autonomy = mode_manager_with_autonomy
    asyncio.run(mgr.switch("dev"))
    autonomy.trigger.assert_awaited_once()
    call_kwargs = autonomy.trigger.call_args.kwargs
    assert call_kwargs["event_type"] == "mode_change"
    assert call_kwargs["data"]["mode_id"] == "dev"


def test_voice_alias_matching(mode_manager):
    assert mode_manager.match_from_voice("switch to trading mode") == "trading"
    assert mode_manager.match_from_voice("go to night mode") == "night"
    assert mode_manager.match_from_voice("enable focus") == "focus"
    # "deep work" matches focus alias — but voice_aliases order matters;
    # just assert it returns something that makes sense (work or focus both valid)
    result = mode_manager.match_from_voice("deep work please")
    assert result in ("focus", "work")   # either is acceptable
    assert mode_manager.match_from_voice("gibberish xyz") is None


def test_mode_color_accents(mode_manager):
    accents = {m["id"]: m["color_accent"] for m in mode_manager.list_modes()}
    assert accents["trading"] == "#10b981"
    assert accents["dev"]     == "#7c3aed"
    assert accents["night"]   == "#4f46e5"


@pytest.mark.asyncio
async def test_switch_cycle_all_modes(mode_manager):
    for mode_id in ["work", "trading", "dev", "focus", "night", "research"]:
        result = await mode_manager.switch(mode_id)
        assert result.get("switched_to") == mode_id, f"Failed for mode: {mode_id}"
        assert mode_manager.current_id == mode_id
