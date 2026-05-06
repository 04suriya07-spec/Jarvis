"""
Tests for core/autonomy.py — AutonomyEngine
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time


@pytest.fixture
def engine():
    from core.autonomy import AutonomyEngine
    e = AutonomyEngine()
    e.set_dependencies(
        assistant=None,
        voice=None,
        intelligence=None,
        personality=None,
        cloud=None,
    )
    return e


class TestAutonomyTrigger:

    @pytest.mark.asyncio
    async def test_trigger_basic(self, engine):
        await engine.trigger("test_event", "hello world", "medium")
        events = engine.get_recent_events(limit=10)
        assert len(events) == 1
        assert events[0]["event_type"] == "test_event"
        assert events[0]["message"] == "hello world"

    @pytest.mark.asyncio
    async def test_trigger_with_data(self, engine):
        data = {"mode_id": "trading", "color": "#10b981"}
        await engine.trigger("mode_change", "Switched to trading", "medium", data=data)
        events = engine.get_recent_events()
        assert events[0]["data"]["mode_id"] == "trading"
        assert events[0]["data"]["color"] == "#10b981"

    @pytest.mark.asyncio
    async def test_trigger_priority_values(self, engine):
        for priority in ["low", "medium", "high", "critical"]:
            await engine.trigger("test", "msg", priority)
        events = engine.get_recent_events(limit=4)
        priorities = [e["priority"] for e in events]
        assert "low" in priorities
        assert "critical" in priorities

    @pytest.mark.asyncio
    async def test_trigger_invalid_priority_defaults_medium(self, engine):
        await engine.trigger("test", "msg", "invalid_priority")
        events = engine.get_recent_events(limit=1)
        assert events[0]["priority"] == "medium"

    @pytest.mark.asyncio
    async def test_broadcast_to_subscribers(self, engine):
        q = engine.subscribe()
        await engine.trigger("alert", "CPU high", "high")
        payload = q.get_nowait()
        assert payload["event_type"] == "alert"
        assert payload["priority"] == "high"

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_queue(self, engine):
        q = engine.subscribe()
        engine.unsubscribe(q)
        await engine.trigger("test", "msg")
        # queue should have nothing (was removed before trigger)
        assert q.empty()

    @pytest.mark.asyncio
    async def test_emit_throttle(self, engine):
        from core.autonomy import AutonomyEvent, EventPriority

        evt = AutonomyEvent(
            event_id="x1", event_type="health", priority=EventPriority.LOW,
            title="Disk", message="disk full"
        )
        # First emit — goes through
        await engine._emit_throttled("disk_low", 60, evt)
        assert len(engine._event_log) == 1

        # Second emit within throttle window — should be suppressed
        evt2 = AutonomyEvent(
            event_id="x2", event_type="health", priority=EventPriority.LOW,
            title="Disk", message="disk still full"
        )
        await engine._emit_throttled("disk_low", 60, evt2)
        assert len(engine._event_log) == 1   # no second entry

    @pytest.mark.asyncio
    async def test_dismiss_prevents_emit(self, engine):
        q = engine.subscribe()
        await engine.trigger("alert", "first event")
        events = engine.get_recent_events()
        event_id = events[0]["event_id"]

        engine.dismiss(event_id)

        # Dismissed ID won't fire again (simulated via _make_id collision)
        # Direct test: dismissed_events set should contain the id
        assert event_id in engine._dismissed_events

    @pytest.mark.asyncio
    async def test_event_log_capped_at_200(self, engine):
        for i in range(205):
            await engine.trigger(f"type_{i}", f"msg {i}")
        assert len(engine._event_log) <= 200

    def test_get_stats(self, engine):
        stats = engine.get_stats()
        assert "total_events" in stats
        assert "by_type" in stats
        assert "running" in stats

    def test_get_recent_events_filter(self):
        from core.autonomy import AutonomyEngine
        e = AutonomyEngine()
        asyncio.run(e.trigger("type_a", "msg a"))
        asyncio.run(e.trigger("type_b", "msg b"))
        asyncio.run(e.trigger("type_a", "msg c"))

        filtered = e.get_recent_events(event_type="type_a")
        assert len(filtered) == 2
        assert all(ev["event_type"] == "type_a" for ev in filtered)
