import asyncio
from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_hedge_waits_for_second_provider_when_first_fails(monkeypatch):
    from core.llm.router import LLMRouter

    router = LLMRouter()
    slots = [
        SimpleNamespace(name="fast_fail", available=True),
        SimpleNamespace(name="slow_success", available=True),
    ]

    async def fake_call_slot(slot, messages, system, max_tokens):
        if slot.name == "fast_fail":
            await asyncio.sleep(0.01)
            raise RuntimeError("provider down")
        await asyncio.sleep(0.05)
        return "Here is the answer you requested.", 10

    monkeypatch.setattr(router, "_call_slot", fake_call_slot)

    text, tokens, winner = await router._hedge(slots, [], "system", 10)

    assert text == "Here is the answer you requested."
    assert tokens == 10
    assert winner == "slow_success"


def test_health_report_exposes_active_provider(monkeypatch):
    from core.llm.router import LLMRouter

    router = LLMRouter()
    first = SimpleNamespace(
        name="groq",
        priority=0,
        available=True,
        health=SimpleNamespace(to_dict=lambda: {"name": "groq"}),
        cb=SimpleNamespace(state=SimpleNamespace(value="closed"), seconds_until_retry=0),
        ucb1_score=lambda: 2.0,
    )
    second = SimpleNamespace(
        name="ollama",
        priority=1,
        available=True,
        health=SimpleNamespace(to_dict=lambda: {"name": "ollama"}),
        cb=SimpleNamespace(state=SimpleNamespace(value="closed"), seconds_until_retry=0),
        ucb1_score=lambda: 1.0,
    )
    router._slots = [second, first]

    report = router.health_report()

    assert report["routing_order"] == ["groq", "ollama"]
    assert report["active_provider"] == "groq"
