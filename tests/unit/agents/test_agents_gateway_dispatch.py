"""Unit tests for agents_gateway_dispatch — packet_ctx shape and retries."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.agents_paths import gateway_admitted_prompt_path
from audiagentic.components.agents.configuration.management import (
    create_execution_profile,
)
from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.queue import dispatch as dispatch
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state
from audiagentic.foundation.io import atomic_write_bytes


def _enable_provider(project_root: Path, provider_id: str) -> None:
    set_implementation_state(project_root, "providers", provider_id, ImplementationState(enabled=True))


def _make_profile(project_root: Path, profile_id: str, provider_id: str, model_id: str = "gpt-4o", **params) -> None:
    create_execution_profile(project_root, {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "instances": [model_id],
        "params": params,
    })
    _enable_provider(project_root, provider_id)


def _record(project_root: Path, execution_profile_id: str, model_id: str = "gpt-4o") -> dict:
    # AS105/AS101: dispatch.py reads the bound model from resolved-model-id,
    # normally injected by queue.py's _run_one at dispatch time. These tests
    # call dispatch.dispatch_request directly, bypassing the queue, so the
    # binding has to be supplied here instead.
    record = store.build_record(
        execution_profile_id=execution_profile_id,
        prompt_body="do the thing",
        resolved_model_id=model_id,
    )
    store.write_record(project_root, record)
    claimed = store.claim_dispatch(
        project_root, record["request-id"], owner_epoch="service-test", expected_revision=0
    )
    return store.start_owned_attempt(
        project_root, record["request-id"], owner_epoch="service-test", worker_id="worker_test",
        expected_revision=claimed["revision"],
    )


def _dispatch(project_root: Path, record: dict, prompt: str = "do the thing") -> dict:
    return dispatch.dispatch_request(
        project_root,
        record,
        dispatch_prompt=prompt,
        manifest_id="mf_test",
        context_fingerprint="0" * 64,
        component_profile="",
        provider_isolation_tier="full-isolation",
        worker_timeout_seconds=10,
    )


def _worker_result(data: dict) -> SimpleNamespace:
    return SimpleNamespace(result_data=data)


def test_classify_failure_prefixes():
    # Terminal (validation/config) — never retried.
    for prefix in ("VAL", "RES", "CON", "CFG", "VER", "UNS"):
        exc = AudiaGenticError(code=f"{prefix}-X-001", kind="agents", message="m")
        assert dispatch.classify_failure(exc) == "validation_config", prefix
    # Transient — retried.
    for prefix in ("NET", "TO", "EXT", "INT", "IO"):
        exc = AudiaGenticError(code=f"{prefix}-X-001", kind="agents", message="m")
        assert dispatch.classify_failure(exc) == "transient", prefix


def test_dispatch_success_builds_expected_packet_ctx(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai", model_id="gpt-4o")
    record = _record(tmp_path, "default")

    captured = {}

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        packet_ctx = execution_request["packet-data"]
        provider_id = execution_request["provider-id"]
        if packet_ctx.get("request-id") != record["request-id"]:
            raise AudiaGenticError(code="NET-STRAY-001", kind="providers", message="not this test's request")
        captured.update(packet_ctx)
        return _worker_result({"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "hi", "completion": {"kind": "completion"}})

    monkeypatch.setattr("audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn", fake_execute_provider)

    # SH02: pass dispatch_prompt separately; the persisted record has prompt-body=None
    result = _dispatch(tmp_path, record)

    assert result["state"] == "completed"
    assert result["output"] == "hi"
    assert result["provider-id"] == "local-openai"
    assert result["model-id"] == "gpt-4o"
    assert captured["request-id"] == record["request-id"]
    assert captured["execution-profile-id"] == "default"
    assert captured["provider-id"] == "local-openai"
    assert captured["prompt-body"] == "do the thing"
    assert captured["working-root"] == str(tmp_path.resolve())
    assert captured["stream-controls"] == {}


def test_worker_dispatch_writes_operator_trace(tmp_path: Path, monkeypatch):
    """Worker-backed (one-shot) sessions use the shared trace sink too."""
    _make_profile(tmp_path, "default", "local-openai", model_id="gpt-4o")
    record = _record(tmp_path, "default")
    trace_path = tmp_path / "gateway-console-trace.log"
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE", "summary")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE_FILE", str(trace_path))

    def fake_execute_provider(*, identity, execution_request, timeout_seconds, activity_callback):
        del identity, execution_request, timeout_seconds, activity_callback
        return _worker_result({"provider-id": "local-openai", "model": "gpt-4o", "output": "worker output"})

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        fake_execute_provider,
    )

    result = _dispatch(tmp_path, record)

    assert result["state"] == "completed"
    rendered = trace_path.read_text(encoding="utf-8")
    assert "START" in rendered and "harness=worker" in rendered
    assert "TURN" in rendered and f"request={record['request-id']}" in rendered
    assert "COMPLETE" in rendered and "output_chars=13" in rendered


def test_worker_dispatch_persists_provider_runtime_metadata(tmp_path: Path, monkeypatch):
    """Opaque provider identity survives the worker-to-record handoff.

    GPT-auto uses these fields to reopen the exact project/chat tab after a
    gateway restart.  The gateway must carry them without interpreting or
    exposing the provider-specific metadata in compact status.
    """
    _make_profile(tmp_path, "default", "local-openai", model_id="gpt-4o")
    record = _record(tmp_path, "default")
    metadata = {
        "project-url": "https://chatgpt.com/g/g-p-example/project",
        "chat-url": "https://chatgpt.com/g/g-p-example/c/c-example",
        "provider-session-id": "session-example",
    }

    def fake_execute_provider(*, identity, execution_request, timeout_seconds, activity_callback):
        del identity, execution_request, timeout_seconds, activity_callback
        return _worker_result(
            {
                "provider-id": "local-openai",
                "model": "gpt-4o",
                "output": "worker output",
                "metadata": metadata,
            }
        )

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        fake_execute_provider,
    )

    result = _dispatch(tmp_path, record)

    assert result["state"] == "completed"
    persisted = store.read_record(tmp_path, record["request-id"])
    assert persisted["provider-metadata"] == metadata


def test_dispatch_reloads_admitted_prompt_snapshot_when_fast_path_is_lost(
    tmp_path: Path, monkeypatch
):
    _make_profile(tmp_path, "default", "local-openai", model_id="gpt-4o")
    record = _record(tmp_path, "default")
    atomic_write_bytes(
        gateway_admitted_prompt_path(tmp_path, record["request-id"]),
        "frozen admitted prompt\r\nwith café".encode(),
    )
    captured: dict[str, object] = {}

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        captured.update(execution_request["packet-data"])
        return _worker_result({"provider-id": "local-openai", "model": "gpt-4o", "output": "ok"})

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        fake_execute_provider,
    )

    result = dispatch.dispatch_request(
        tmp_path,
        record,
        dispatch_prompt=None,  # type: ignore[arg-type]
        manifest_id="mf_test",
        context_fingerprint="0" * 64,
        component_profile="",
        provider_isolation_tier="full-isolation",
        worker_timeout_seconds=10,
    )

    assert result["state"] == "completed"
    assert captured["prompt-body"] == "frozen admitted prompt\r\nwith café"


def test_dispatch_uses_profile_stream_controls_and_ignores_metadata_working_root(
    tmp_path: Path, monkeypatch
):
    _make_profile(
        tmp_path,
        "default",
        "local-openai",
        **{"stream-controls": {"enabled": True, "tee-console": False}},
    )
    record = _record(tmp_path, "default")
    record["metadata"] = {"working-root": "C:/untrusted"}
    store.write_record(tmp_path, record)
    captured = {}

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        packet_ctx = execution_request["packet-data"]
        provider_id = execution_request["provider-id"]
        captured.update(packet_ctx)
        return _worker_result({"provider-id": provider_id, "model": "gpt-4o", "output": "ok"})

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        fake_execute_provider,
    )

    result = _dispatch(tmp_path, record)

    assert result["state"] == "completed"
    assert captured["working-root"] == str(tmp_path.resolve())
    assert captured["stream-controls"] == {"enabled": True, "tee-console": False}


def test_dispatch_retries_transient_then_succeeds(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai", **{"retry-count": 2})
    record = _record(tmp_path, "default")

    calls = {"count": 0}

    def flaky_execute_provider(*, identity, execution_request, timeout_seconds):
        packet_ctx = execution_request["packet-data"]
        provider_id = execution_request["provider-id"]
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
        return _worker_result({"provider-id": provider_id, "status": "ok", "model": "gpt-4o", "output": "recovered"})

    monkeypatch.setattr("audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn", flaky_execute_provider)

    result = _dispatch(tmp_path, record)

    assert result["state"] == "completed"
    assert result["output"] == "recovered"
    assert calls["count"] == 3
    assert len(result["attempts"]) == 3
    assert [a["state"] for a in result["attempts"]] == ["failed", "failed", "completed"]


def test_retry_attempts_keep_admitted_prompt_after_source_mutation(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "default", "local-openai", **{"retry-count": 1})
    record = _record(tmp_path, "default")
    frozen = "admitted café\nsecond line"
    atomic_write_bytes(gateway_admitted_prompt_path(tmp_path, record["request-id"]), frozen.encode("utf-8"))
    observed: list[str] = []
    calls = {"count": 0}

    def flaky_execute_provider(*, identity, execution_request, timeout_seconds):
        calls["count"] += 1
        observed.append(execution_request["packet-data"]["prompt-body"])
        if calls["count"] == 1:
            # Simulate a source/config mutation between retry attempts.  The
            # dispatch loop must retain the request-owned admitted bytes.
            atomic_write_bytes(
                gateway_admitted_prompt_path(tmp_path, record["request-id"]),
                b"mutated source",
            )
            raise AudiaGenticError(code="NET-FAKE-001", kind="providers", message="retry")
        return _worker_result({"provider-id": "local-openai", "model": "gpt-4o", "output": "ok"})

    monkeypatch.setattr(
        "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
        flaky_execute_provider,
    )
    result = dispatch.dispatch_request(
        tmp_path,
        record,
        dispatch_prompt=None,  # reload the durable snapshot, not mutable config
        manifest_id="mf_test",
        context_fingerprint="0" * 64,
        component_profile="",
        provider_isolation_tier="full-isolation",
        worker_timeout_seconds=10,
    )
    assert result["state"] == "completed"
    assert observed == [frozen, frozen]


def test_dispatch_validation_error_is_terminal(tmp_path: Path, monkeypatch):
    _make_profile(tmp_path, "primary", "local-openai")
    record = _record(tmp_path, "primary")

    def fake_execute_provider(**_kwargs):
        raise AudiaGenticError(code="VAL-FAKE-001", kind="providers", message="bad request")

    monkeypatch.setattr("audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn", fake_execute_provider)

    result = _dispatch(tmp_path, record)

    assert result["state"] == "failed"
    assert result["error"]["code"] == "VAL-FAKE-001"
    # exactly one attempt — validation errors do not retry
    assert len(result["attempts"]) == 1
    assert result["attempts"][0]["execution-profile-id"] == "primary"


def test_dispatch_disabled_provider_is_terminal(tmp_path: Path, monkeypatch):
    create_execution_profile(tmp_path, {"profile_id": "primary", "provider_id": "local-openai", "instances": ["gpt-4o"]})
    # provider left disabled (never enabled)
    record = _record(tmp_path, "primary")

    calls = {"count": 0}

    def fake_execute_provider(**_kwargs):
        calls["count"] += 1
        raise AudiaGenticError(code="CFG-PEXE-001", kind="providers", message="provider disabled")

    monkeypatch.setattr("audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn", fake_execute_provider)

    result = _dispatch(tmp_path, record)

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

    def fake_execute_provider(*, identity, execution_request, timeout_seconds):
        packet_ctx = execution_request["packet-data"]
        if packet_ctx.get("request-id") != record["request-id"]:
            raise AudiaGenticError(code="NET-STRAY-001", kind="providers", message="not this test's request")
        calls["count"] += 1
        if calls["count"] == 1:
            store.mark_cancel_requested(tmp_path, record["request-id"])
        raise AudiaGenticError(code="NET-FAKE-001", kind="providers", message="down")

    monkeypatch.setattr("audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn", fake_execute_provider)

    result = _dispatch(tmp_path, record)

    assert result["state"] == "cancelled"
    # attempt 1 ran and failed, then the cancel flag stopped attempt 2 —
    # nowhere near the configured retry-count of 5 additional attempts.
    assert calls["count"] == 1
    assert len(result["attempts"]) == 1


def test_resolve_retry_count_default_and_validation():
    assert dispatch.resolve_retry_count({}) == 1
    with pytest.raises(AudiaGenticError) as exc_info:
        dispatch.resolve_retry_count({"retry-count": -1})
    assert exc_info.value.code == "VAL-AGW-030"
