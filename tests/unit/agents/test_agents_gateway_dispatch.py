"""Unit tests for agents_gateway_dispatch — packet_ctx shape, retry on
transient failure, fallback profile order, and no-fallback for
validation/config errors (AG10), using an injected fake execute_provider."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents import agents_gateway_dispatch as dispatch
from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.components.agents.agents_api import create_profile
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state


def _enable_provider(project_root: Path, provider_id: str) -> None:
    set_implementation_state(project_root, "providers", provider_id, ImplementationState(enabled=True))


def _make_profile(project_root: Path, profile_id: str, provider_id: str, model_id: str = "gpt-4o", **params) -> None:
    create_profile(project_root, {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "model_id": model_id,
        "params": params,
    })
    _enable_provider(project_root, provider_id)


def _record(project_root: Path, agent_profile_id: str, fallback_profile_ids=None) -> dict:
    record = store.build_record(
        agent_profile_id=agent_profile_id,
        prompt_body="do the thing",
        fallback_profile_ids=fallback_profile_ids or [],
    )
    store.write_record(project_root, record)
    return store.transition_record(project_root, record["request-id"], "running")


def test_classify_failure_prefixes():
    # Terminal (validation/config) — never retried, never triggers fallback.
    for prefix in ("VAL", "RES", "CON", "CFG", "VER", "UNS"):
        exc = AudiaGenticError(code=f"{prefix}-X-001", kind="agents", message="m")
        assert dispatch.classify_failure(exc) == "validation_config", prefix
    # Transient — retried, then falls back to the next profile.
    for prefix in ("NET", "TO", "EXT", "INT", "IO"):
        exc = AudiaGenticError(code=f"{prefix}-X-001", kind="agents", message="m")
        assert dispatch.classify_failure(exc) == "transient", prefix


def test_dispatch_success_builds_expected_packet_ctx(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai", model_id="gpt-4o")
    record = _record(tmp_path, "default")

    captured = {}

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        if packet_ctx.get("request-id") != record["request-id"]:
            raise AudiaGenticError(code="NET-STRAY-001", kind="providers", message="not this test's request")
        captured.update(packet_ctx)
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "hi", "completion": {"kind": "completion"}}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    result = dispatch.dispatch_request(tmp_path, record)

    assert result["state"] == "completed"
    assert result["output"] == "hi"
    assert result["provider-id"] == "local-openai"
    assert result["model-id"] == "gpt-4o"
    assert captured["request-id"] == record["request-id"]
    assert captured["agent-profile-id"] == "default"
    assert captured["provider-id"] == "local-openai"
    assert captured["prompt-body"] == "do the thing"


def test_dispatch_retries_transient_then_succeeds(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai", **{"retry-count": 2})
    record = _record(tmp_path, "default")

    calls = {"count": 0}

    def flaky_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        # execute_provider is monkeypatched process-wide — a straggler
        # background thread from an earlier (unrelated) test's queue-manager
        # worker can still be mid-flight and call through this same patched
        # function. Filter to this test's own request-id so a stray call
        # never corrupts the count.
        if packet_ctx.get("request-id") != record["request-id"]:
            raise AudiaGenticError(code="NET-STRAY-001", kind="providers", message="not this test's request")
        calls["count"] += 1
        if calls["count"] < 3:
            raise AudiaGenticError(code="NET-FAKE-001", kind="providers", message="connection reset")
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "recovered"}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", flaky_execute_provider)

    result = dispatch.dispatch_request(tmp_path, record)

    assert result["state"] == "completed"
    assert result["output"] == "recovered"
    assert calls["count"] == 3
    assert len(result["attempts"]) == 3
    assert [a["state"] for a in result["attempts"]] == ["failed", "failed", "completed"]


def test_dispatch_falls_back_to_second_profile_after_retries_exhausted(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "primary", "local-openai", **{"retry-count": 0})
    _make_profile(tmp_path, "backup", "codex", **{"retry-count": 0})
    record = _record(tmp_path, "primary", fallback_profile_ids=["backup"])

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        if provider_id == "local-openai":
            raise AudiaGenticError(code="EXT-FAKE-001", kind="providers", message="primary down")
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "from backup"}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    result = dispatch.dispatch_request(tmp_path, record)

    assert result["state"] == "completed"
    assert result["provider-id"] == "codex"
    assert result["output"] == "from backup"
    profiles_tried = [a["agent-profile-id"] for a in result["attempts"]]
    assert profiles_tried == ["primary", "backup"]


def test_dispatch_no_fallback_on_validation_error(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "primary", "local-openai")
    _make_profile(tmp_path, "backup", "codex")
    record = _record(tmp_path, "primary", fallback_profile_ids=["backup"])

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        raise AudiaGenticError(code="VAL-FAKE-001", kind="providers", message="bad request")

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    result = dispatch.dispatch_request(tmp_path, record)

    assert result["state"] == "failed"
    assert result["error"]["code"] == "VAL-FAKE-001"
    # exactly one attempt — fallback was never tried
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["agent-profile-id"] == "primary"


def test_dispatch_disabled_provider_is_terminal_no_fallback(tmp_path: Path, monkeypatch):
    create_profile(tmp_path, {"profile_id": "primary", "provider_id": "local-openai", "model_id": "gpt-4o"})
    # provider left disabled (never enabled)
    create_profile(tmp_path, {"profile_id": "backup", "provider_id": "codex", "model_id": "gpt-4o"})
    _enable_provider(tmp_path, "codex")
    record = _record(tmp_path, "primary", fallback_profile_ids=["backup"])

    calls = {"count": 0}

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        if packet_ctx.get("request-id") != record["request-id"]:
            raise AudiaGenticError(code="NET-STRAY-001", kind="providers", message="not this test's request")
        calls["count"] += 1
        return {"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "should not be called"}

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    result = dispatch.dispatch_request(tmp_path, record)

    assert result["state"] == "failed"
    assert result["error"]["code"] == "VAL-AGW-031"
    assert calls["count"] == 0


def test_dispatch_stops_retrying_once_cancel_requested(tmp_path: Path, monkeypatch):
    """RV23: the retry loop must not blindly burn through retry-count once a
    cancel has been recorded — it should stop and transition to 'cancelled'
    rather than continuing to dispatch attempts nobody wants anymore."""
    _make_profile(tmp_path, "default", "local-openai", **{"retry-count": 5})
    record = _record(tmp_path, "default")

    calls = {"count": 0}

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        if packet_ctx.get("request-id") != record["request-id"]:
            raise AudiaGenticError(code="NET-STRAY-001", kind="providers", message="not this test's request")
        calls["count"] += 1
        if calls["count"] == 1:
            store.mark_cancel_requested(tmp_path, record["request-id"])
        raise AudiaGenticError(code="NET-FAKE-001", kind="providers", message="down")

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    result = dispatch.dispatch_request(tmp_path, record)

    assert result["state"] == "cancelled"
    # attempt 1 ran and failed, then the cancel flag stopped attempt 2 —
    # nowhere near the configured retry-count of 5 additional attempts.
    assert calls["count"] == 1
    assert len(result["attempts"]) == 1


def test_dispatch_stops_before_fallback_once_cancel_requested(tmp_path: Path, monkeypatch):
    """RV23: cancel observed between exhausting the primary profile and
    trying a fallback profile must stop the fallback from ever starting."""
    _make_profile(tmp_path, "primary", "local-openai", **{"retry-count": 0})
    _make_profile(tmp_path, "backup", "codex", **{"retry-count": 0})
    record = _record(tmp_path, "primary", fallback_profile_ids=["backup"])

    def fake_execute_provider(*, provider_id, packet_ctx, provider_cfg):
        if packet_ctx.get("request-id") != record["request-id"]:
            raise AudiaGenticError(code="NET-STRAY-001", kind="providers", message="not this test's request")
        if provider_id == "local-openai":
            store.mark_cancel_requested(tmp_path, record["request-id"])
            raise AudiaGenticError(code="EXT-FAKE-001", kind="providers", message="primary down")
        raise AssertionError("fallback profile should never be dispatched once cancelled")

    monkeypatch.setattr("audiagentic.components.providers.services.execution.execute_provider", fake_execute_provider)

    result = dispatch.dispatch_request(tmp_path, record)

    assert result["state"] == "cancelled"
    profiles_tried = [a["agent-profile-id"] for a in result["attempts"]]
    assert profiles_tried == ["primary"]


def test_resolve_retry_count_default_and_validation():
    assert dispatch.resolve_retry_count({}) == 1
    with pytest.raises(AudiaGenticError) as exc_info:
        dispatch.resolve_retry_count({"retry-count": -1})
    assert exc_info.value.code == "VAL-AGW-030"
