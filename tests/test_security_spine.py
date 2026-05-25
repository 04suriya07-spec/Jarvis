import json

import pytest


def test_policy_blocks_send_external_by_default():
    from core.policy import PolicyEngine

    policy = PolicyEngine()
    decision = policy.evaluate("email", {"action": "send", "to": "a@example.com"})

    assert decision.allowed is False
    assert decision.requires_approval is True
    assert decision.risk == "send_external"


def test_policy_allows_after_approval():
    from core.policy import PolicyEngine

    policy = PolicyEngine()
    params = {"action": "send", "to": "a@example.com"}
    first = policy.evaluate("email", params)
    policy.approve(first.action_hash)
    second = policy.evaluate("email", params)

    assert second.allowed is True
    assert second.requires_approval is True


def test_redaction_masks_secret_values():
    from core.security.redaction import redact_value

    redacted = redact_value({"api_key": "sk-secret123", "nested": {"password": "abc"}})

    assert redacted["api_key"] == "<redacted>"
    assert redacted["nested"]["password"] == "<redacted>"


def test_audit_log_redacts(tmp_path):
    from core.audit import AuditLog
    from core.models import RiskLevel, SkillResult

    audit = AuditLog(path=tmp_path / "audit.jsonl")
    audit.write(
        action="tool:test",
        risk=RiskLevel.CREDENTIAL_ACCESS,
        input_data={"token": "secret-token"},
        result=SkillResult(ok=False, error="no"),
    )

    line = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    payload = json.loads(line)
    assert payload["input"]["token"] == "<redacted>"


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    from core.events import EventBus

    bus = EventBus()
    q = bus.subscribe()
    await bus.publish("hello", {"x": 1}, trace_id="t1")
    event = q.get_nowait()

    assert event["type"] == "hello"
    assert event["trace_id"] == "t1"
    assert event["data"]["x"] == 1
