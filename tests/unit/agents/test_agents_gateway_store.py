"""Unit tests for agents_gateway_store — record contract, atomic persistence,
state transitions, and error redaction (AG08)."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest

from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_build_record_defaults(tmp_path: Path) -> None:
    record = store.build_record(agent_profile_id="default", prompt_body="do the thing")
    assert record["state"] == "queued"
    assert record["mode"] == "async"
    assert record["fallback-profile-ids"] == []
    assert record["attempts"] == []
    assert record["cancel-requested"] is False
    assert record["request-id"].startswith("req_")


def test_build_record_rejects_invalid_mode() -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(agent_profile_id="default", prompt_body="x", mode="sync")
    assert exc_info.value.code == "VAL-AGW-001"


def test_build_record_rejects_missing_prompt_body() -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(agent_profile_id="default", prompt_body=None)
    assert exc_info.value.code == "VAL-AGW-007"


def test_build_record_rejects_empty_prompt_body() -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(agent_profile_id="default", prompt_body="   ")
    assert exc_info.value.code == "VAL-AGW-007"


def test_build_record_rejects_non_positive_timeout(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(agent_profile_id="default", prompt_body="x", timeout_seconds=0)
    assert exc_info.value.code == "VAL-AGW-008"

    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(agent_profile_id="default", prompt_body="x", timeout_seconds=-5)
    assert exc_info.value.code == "VAL-AGW-008"


def test_build_record_rejects_string_fallback_profile_ids() -> None:
    """A bare string is iterable, so 'backup' would silently explode into
    ['b','a','c','k','u','p'] without this check (RV30)."""
    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(agent_profile_id="default", prompt_body="x", fallback_profile_ids="backup")
    assert exc_info.value.code == "VAL-AGW-009"


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    fetched = store.read_record(tmp_path, record["request-id"])
    assert fetched == record


def test_read_missing_record_raises(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.read_record(tmp_path, "req_doesnotexist")
    assert exc_info.value.code == "RES-AGW-001"


def test_list_records_returns_all(tmp_path: Path) -> None:
    r1 = store.build_record(agent_profile_id="default", prompt_body="a")
    r2 = store.build_record(agent_profile_id="default", prompt_body="b")
    store.write_record(tmp_path, r1)
    store.write_record(tmp_path, r2)
    ids = {r["request-id"] for r in store.list_records(tmp_path)}
    assert ids == {r1["request-id"], r2["request-id"]}


def test_list_records_empty_when_no_gateway_dir(tmp_path: Path) -> None:
    assert store.list_records(tmp_path) == []


def test_transition_record_queued_to_running(tmp_path: Path) -> None:
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    updated = store.transition_record(
        tmp_path, record["request-id"], "running",
        updates={"provider-id": "local-openai", "model-id": "gpt-4o", "started-at": "2026-01-01T00:00:00Z"},
    )
    assert updated["state"] == "running"
    assert updated["provider-id"] == "local-openai"
    assert updated["started-at"] == "2026-01-01T00:00:00Z"


def test_transition_record_illegal_transition_raises(tmp_path: Path) -> None:
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    with pytest.raises(AudiaGenticError) as exc_info:
        store.transition_record(tmp_path, record["request-id"], "completed")
    assert exc_info.value.code == "CON-AGW-001"


def test_transition_record_redacts_error(tmp_path: Path) -> None:
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    err = AudiaGenticError(
        code="EXT-CLAUDE-001",
        kind="providers",
        message="claude execution failed",
        details={"stdout": "SECRET_TOKEN=abc123", "command": ["claude", "--print"]},
    )
    updated = store.transition_record(
        tmp_path, record["request-id"], "failed", updates={"error": err},
    )
    assert updated["error"] == {"code": "EXT-CLAUDE-001", "message": "claude execution failed", "kind": "providers"}
    assert "SECRET_TOKEN" not in str(updated["error"])
    assert "stdout" not in updated["error"]


def test_transition_record_redacts_generic_exception_message(tmp_path: Path) -> None:
    """A non-AudiaGenticError exception's str() must not be persisted verbatim —
    it carries none of AudiaGenticError's own redaction guarantees and could
    embed prompt/stdout/token content (RV21 finding)."""
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    leaky = RuntimeError("connection to https://x?token=SECRET_TOKEN_ABC failed, stdout was: dump-of-prompt")
    updated = store.transition_record(
        tmp_path, record["request-id"], "failed", updates={"error": leaky},
    )
    assert "SECRET_TOKEN_ABC" not in str(updated["error"])
    assert "dump-of-prompt" not in str(updated["error"])
    assert updated["error"]["kind"] == "RuntimeError"


def test_schema_rejects_additional_properties(tmp_path: Path) -> None:
    """additionalProperties: false — a 'messages' field (never part of the v1
    contract; see RV12) must fail validation rather than pass through silently."""
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    record["messages"] = [{"role": "user", "content": "hi"}]
    with pytest.raises(AudiaGenticError) as exc_info:
        store.write_record(tmp_path, record)
    assert exc_info.value.code == "VAL-AGW-004"


def test_mark_cancel_requested_persists_flag(tmp_path: Path) -> None:
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    updated = store.mark_cancel_requested(tmp_path, record["request-id"])
    assert updated["cancel-requested"] is True
    # observable independent of any in-memory queue manager state
    fetched = store.read_record(tmp_path, record["request-id"])
    assert fetched["cancel-requested"] is True


def test_mark_cancel_requested_is_idempotent(tmp_path: Path) -> None:
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    store.mark_cancel_requested(tmp_path, record["request-id"])
    updated = store.mark_cancel_requested(tmp_path, record["request-id"])
    assert updated["cancel-requested"] is True


def test_concurrent_mark_cancel_requested_and_append_attempt_do_not_clobber(tmp_path: Path) -> None:
    """RV31: without per-request locking, a cancel racing a dispatch worker's
    attempt append is a lost-update — whichever read-modify-write lands last
    silently discards the other's change. Hammer both concurrently and assert
    neither is ever lost."""
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    request_id = record["request-id"]

    iterations = 50
    errors: list[Exception] = []

    def cancel_repeatedly() -> None:
        try:
            for _ in range(iterations):
                store.mark_cancel_requested(tmp_path, request_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    def append_repeatedly() -> None:
        try:
            for i in range(iterations):
                store.append_attempt(
                    tmp_path, request_id,
                    agent_profile_id="default", provider_id="local-openai", model_id="gpt-4o",
                    state="failed", started_at=f"2026-01-01T00:00:{i:02d}Z",
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=cancel_repeatedly)
    t2 = threading.Thread(target=append_repeatedly)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, errors
    final = store.read_record(tmp_path, request_id)
    assert final["cancel-requested"] is True
    assert len(final["attempts"]) == iterations


def test_append_attempt_does_not_change_state(tmp_path: Path) -> None:
    record = store.build_record(agent_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    updated = store.append_attempt(
        tmp_path, record["request-id"],
        agent_profile_id="default", provider_id="local-openai", model_id="gpt-4o",
        state="running", started_at="2026-01-01T00:00:00Z",
    )
    assert updated["state"] == "queued"
    assert len(updated["attempts"]) == 1
    assert updated["attempts"][0]["agent-profile-id"] == "default"


def test_terminal_states() -> None:
    assert store.TERMINAL_STATES == {"completed", "failed", "cancelled", "rejected"}
