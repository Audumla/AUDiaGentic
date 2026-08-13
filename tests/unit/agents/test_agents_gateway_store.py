"""Unit tests for agents_gateway_store — record contract, atomic persistence,
state transitions, and error redaction (AG08)."""
from __future__ import annotations

import functools
import json
import multiprocessing
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from audiagentic.components.agents.agents_paths import (
    gateway_idempotency_index_path,
    gateway_request_path,
    gateway_timeline_path,
)
from audiagentic.components.agents.gateway import store as store
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, load_ndjson


def test_build_record_defaults(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="do the thing")
    assert record["state"] == "queued"
    assert record["mode"] == "async"
    assert "fallback-profile-ids" not in record
    assert record["attempts"] == []
    assert record["cancel-requested"] is False
    assert record["request-id"].startswith("req_")


def test_value_error_detail_is_preserved_for_operator_diagnosis(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="do the thing")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    updated = store.transition_record(
        tmp_path,
        record["request-id"],
        "failed",
        updates={"error": ValueError("browser executable is not configured")},
    )
    assert updated["error"] == {
        "code": "VAL-AGW-UNKNOWN",
        "message": "browser executable is not configured",
        "kind": "ValueError",
    }


def test_build_record_rejects_invalid_mode() -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(execution_profile_id="default", prompt_body="x", mode="sync")
    assert exc_info.value.code == "VAL-AGW-001"


def test_build_record_rejects_missing_prompt_body() -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(execution_profile_id="default", prompt_body=None)
    assert exc_info.value.code == "VAL-AGW-007"


def test_build_record_rejects_empty_prompt_body() -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(execution_profile_id="default", prompt_body="   ")
    assert exc_info.value.code == "VAL-AGW-007"


def test_build_record_rejects_non_positive_timeout(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(execution_profile_id="default", prompt_body="x", timeout_seconds=0)
    assert exc_info.value.code == "VAL-AGW-008"

    with pytest.raises(AudiaGenticError) as exc_info:
        store.build_record(execution_profile_id="default", prompt_body="x", timeout_seconds=-5)
    assert exc_info.value.code == "VAL-AGW-008"


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    """SH02: prompt-body is redacted before persistence; only digest survives."""
    record = store.build_record(
        execution_profile_id="default",
        prompt_body="hello",
        manifest_id="mf_test123",
        context_fingerprint="fp" * 32,
        prompt_digest="digest123",
    )
    store.write_record(tmp_path, record)
    fetched = store.read_record(tmp_path, record["request-id"])

    # SH02: prompt-body is redacted before persistence
    assert fetched["prompt-body"] is None
    # But manifest fields survive
    assert fetched["manifest-id"] == "mf_test123"
    assert fetched["context-fingerprint"] == "fp" * 32
    assert fetched["prompt-digest"] == "digest123"
    # Other fields round-trip correctly
    for key in ("request-id", "execution-profile-id", "mode", "state", "contract-version"):
        assert fetched[key] == record[key], f"{key} mismatch"


def test_admit_record_replays_same_key_and_intent_without_raw_key(tmp_path: Path) -> None:
    raw_key = "customer-request-opaque-key"
    first, created = store.admit_record(
        tmp_path,
        store.build_record(
            execution_profile_id="default",
            prompt_body="private prompt",
            context_fingerprint="a" * 64,
            prompt_digest="b" * 64,
        ),
        idempotency_key=raw_key,
    )
    replay, replay_created = store.admit_record(
        tmp_path,
        store.build_record(
            execution_profile_id="default",
            prompt_body="private prompt",
            context_fingerprint="a" * 64,
            prompt_digest="b" * 64,
        ),
        idempotency_key=raw_key,
    )

    assert created is True
    assert replay_created is False
    assert replay["request-id"] == first["request-id"]
    assert replay["prompt-body"] is None
    key_digest = store.hash_idempotency_key(raw_key)
    assert store.read_record(tmp_path, first["request-id"])["idempotency-key"] == key_digest
    index_path = gateway_idempotency_index_path(tmp_path, key_digest)
    assert raw_key not in index_path.read_text(encoding="utf-8")
    assert raw_key not in gateway_request_path(tmp_path, first["request-id"]).read_text(encoding="utf-8")


def test_admit_record_rejects_same_key_with_different_intent(tmp_path: Path) -> None:
    store.admit_record(
        tmp_path,
        store.build_record(
            execution_profile_id="default", prompt_body="first", prompt_digest="a" * 64,
            context_fingerprint="b" * 64,
        ),
        idempotency_key="same-key",
    )

    with pytest.raises(AudiaGenticError, match="CON-AGW-081"):
        store.admit_record(
            tmp_path,
            store.build_record(
                execution_profile_id="default", prompt_body="second", prompt_digest="c" * 64,
                context_fingerprint="b" * 64,
            ),
            idempotency_key="same-key",
        )


def test_admit_record_repairs_stale_index_then_uses_persisted_intent_as_authority(
    tmp_path: Path,
) -> None:
    """A well-formed stale index cannot override the durable request record."""
    raw_key = "stale-index-key"
    original, _ = store.admit_record(
        tmp_path,
        store.build_record(
            execution_profile_id="default", prompt_body="original", prompt_digest="a" * 64,
            context_fingerprint="b" * 64,
        ),
        idempotency_key=raw_key,
    )
    changed = store.build_record(
        execution_profile_id="default", prompt_body="changed", prompt_digest="c" * 64,
        context_fingerprint="b" * 64,
    )
    key_digest = store.hash_idempotency_key(raw_key)
    index_path = gateway_idempotency_index_path(tmp_path, key_digest)
    # The stale entry is structurally valid and points to a real record, but
    # advertises the contender's different intent.
    atomic_write_json(index_path, {
        "key-digest": key_digest,
        "intent-digest": store._intent_digest(changed),
        "request-id": original["request-id"],
    })

    with pytest.raises(AudiaGenticError, match="CON-AGW-081"):
        store.admit_record(tmp_path, changed, idempotency_key=raw_key)

    repaired = json.loads(index_path.read_text(encoding="utf-8"))
    assert repaired == {
        "key-digest": key_digest,
        "intent-digest": store._intent_digest(original),
        "request-id": original["request-id"],
    }
    replay, created = store.admit_record(
        tmp_path,
        store.build_record(
            execution_profile_id="default", prompt_body="original", prompt_digest="a" * 64,
            context_fingerprint="b" * 64,
        ),
        idempotency_key=raw_key,
    )
    assert created is False
    assert replay["request-id"] == original["request-id"]


def test_concurrent_admission_creates_one_record_for_one_key(tmp_path: Path) -> None:
    barrier = threading.Barrier(8)
    results: list[tuple[str, bool]] = []
    errors: list[BaseException] = []

    def submit() -> None:
        try:
            candidate = store.build_record(
                execution_profile_id="default", prompt_body="private", prompt_digest="a" * 64,
                context_fingerprint="b" * 64,
            )
            barrier.wait(timeout=5)
            record, created = store.admit_record(tmp_path, candidate, idempotency_key="one-key")
            results.append((record["request-id"], created))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=submit) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors, errors
    assert {request_id for request_id, _ in results}
    assert len({request_id for request_id, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert len(store.list_records(tmp_path)) == 1


@pytest.mark.no_parallel
def test_cross_process_admission_creates_one_record_for_one_key(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(
            target=functools.partial(
                store.admit_record,
                tmp_path,
                store.build_record(
                    execution_profile_id="default", prompt_body="private", prompt_digest="a" * 64,
                    context_fingerprint="b" * 64,
                ),
                idempotency_key="cross-process-key",
            ),
        )
        for _ in range(8)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)

    assert [process.exitcode for process in processes] == [0] * len(processes)
    records = store.list_records(tmp_path)
    assert len(records) == 1
    assert records[0]["idempotency-key"] == store.hash_idempotency_key("cross-process-key")


@pytest.mark.no_parallel
def test_cross_process_divergent_intents_have_one_winner_and_conflicts(tmp_path: Path) -> None:
    """The admission lock serializes unlike intents without duplicate records."""
    contender_count = 4
    worker = """
import json
import sys
from pathlib import Path

from audiagentic.components.agents.gateway import store as store
from audiagentic.foundation.contracts.errors import AudiaGenticError

try:
    record, created = store.admit_record(
        Path(sys.argv[1]),
        store.build_record(
            execution_profile_id=\"default\",
            prompt_body=\"private\",
            prompt_digest=sys.argv[2],
            context_fingerprint=\"b\" * 64,
        ),
        idempotency_key=\"cross-process-divergent-key\",
    )
except AudiaGenticError as exc:
    print(json.dumps({\"outcome\": \"rejected\", \"code\": exc.code}))
else:
    print(json.dumps({\"outcome\": \"admitted\", \"created\": created, \"request-id\": record[\"request-id\"]}))
"""
    environment = dict(os.environ)
    source_root = str(Path(__file__).resolve().parents[3] / "src")
    environment["PYTHONPATH"] = source_root + os.pathsep + environment.get("PYTHONPATH", "")
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", worker, str(tmp_path), f"{index:x}" * 64],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        for index in range(contender_count)
    ]
    completed = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0] * contender_count, completed
    observed = [json.loads(stdout) for stdout, _stderr in completed]
    winners = [outcome for outcome in observed if outcome["outcome"] == "admitted"]
    conflicts = [outcome for outcome in observed if outcome["outcome"] == "rejected"]
    assert len(winners) == 1
    assert winners[0]["created"] is True
    assert [outcome["code"] for outcome in conflicts] == ["CON-AGW-081"] * (contender_count - 1)
    assert len(store.list_records(tmp_path)) == 1


def test_admit_record_recovers_missing_index_from_persisted_record(tmp_path: Path) -> None:
    raw_key = "recover-index"
    first, _ = store.admit_record(
        tmp_path,
        store.build_record(
            execution_profile_id="default", prompt_body="private", prompt_digest="a" * 64,
            context_fingerprint="b" * 64,
        ),
        idempotency_key=raw_key,
    )
    index_path = gateway_idempotency_index_path(tmp_path, store.hash_idempotency_key(raw_key))
    index_path.unlink()

    replay, created = store.admit_record(
        tmp_path,
        store.build_record(
            execution_profile_id="default", prompt_body="private", prompt_digest="a" * 64,
            context_fingerprint="b" * 64,
        ),
        idempotency_key=raw_key,
    )

    assert created is False
    assert replay["request-id"] == first["request-id"]
    assert index_path.exists()


def test_admit_record_recovers_orphaned_index_without_reviving_lost_prompt(tmp_path: Path) -> None:
    raw_key = "recover-orphan"
    first, _ = store.admit_record(
        tmp_path,
        store.build_record(
            execution_profile_id="default", prompt_body="lost prompt", prompt_digest="a" * 64,
            context_fingerprint="b" * 64,
        ),
        idempotency_key=raw_key,
    )
    gateway_request_path(tmp_path, first["request-id"]).unlink()

    admitted, created = store.admit_record(
        tmp_path,
        store.build_record(
            execution_profile_id="default", prompt_body="replacement prompt", prompt_digest="c" * 64,
            context_fingerprint="b" * 64,
        ),
        idempotency_key=raw_key,
    )

    assert created is True
    assert admitted["request-id"] != first["request-id"]


def test_read_missing_record_raises(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError) as exc_info:
        store.read_record(tmp_path, "req_doesnotexist")
    assert exc_info.value.code == "RES-AGW-001"


def test_list_records_returns_all(tmp_path: Path) -> None:
    r1 = store.build_record(execution_profile_id="default", prompt_body="a")
    r2 = store.build_record(execution_profile_id="default", prompt_body="b")
    store.write_record(tmp_path, r1)
    store.write_record(tmp_path, r2)
    ids = {r["request-id"] for r in store.list_records(tmp_path)}
    assert ids == {r1["request-id"], r2["request-id"]}


def test_list_records_empty_when_no_gateway_dir(tmp_path: Path) -> None:
    assert store.list_records(tmp_path) == []


def test_transition_record_queued_to_running(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    updated = store.transition_record(
        tmp_path, record["request-id"], "running",
        updates={"provider-id": "local-openai", "model-id": "gpt-4o", "started-at": "2026-01-01T00:00:00Z"},
    )
    assert updated["state"] == "running"
    assert updated["provider-id"] == "local-openai"
    assert updated["started-at"] == "2026-01-01T00:00:00Z"
    timeline = load_ndjson(gateway_timeline_path(tmp_path, record["request-id"]))
    assert timeline[-1]["event"] == "state.changed"
    assert "correlation-id" in timeline[-1]
    assert timeline[-1]["state"] == "running"
    assert timeline[-1]["attributes"]["from"] == "queued"
    assert timeline[-1]["attributes"]["to"] == "running"


def test_transition_record_illegal_transition_raises(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    with pytest.raises(AudiaGenticError) as exc_info:
        store.transition_record(tmp_path, record["request-id"], "completed")
    assert exc_info.value.code == "CON-AGW-001"


def test_transition_record_redacts_error(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
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
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
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
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    record["messages"] = [{"role": "user", "content": "hi"}]
    with pytest.raises(AudiaGenticError) as exc_info:
        store.write_record(tmp_path, record)
    assert exc_info.value.code == "VAL-AGW-004"


def test_mark_cancel_requested_persists_flag(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    updated = store.mark_cancel_requested(tmp_path, record["request-id"])
    assert updated["cancel-requested"] is True
    # observable independent of any in-memory queue manager state
    fetched = store.read_record(tmp_path, record["request-id"])
    assert fetched["cancel-requested"] is True
    timeline = load_ndjson(gateway_timeline_path(tmp_path, record["request-id"]))
    assert timeline[-1]["event"] == "cancel.requested"


def test_mark_cancel_requested_is_idempotent(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    store.mark_cancel_requested(tmp_path, record["request-id"])
    updated = store.mark_cancel_requested(tmp_path, record["request-id"])
    assert updated["cancel-requested"] is True


def test_concurrent_mark_cancel_requested_and_append_attempt_do_not_clobber(tmp_path: Path) -> None:
    """A cancel racing a dispatch worker's
    attempt append is a lost-update — whichever read-modify-write lands last
    silently discards the other's change. Hammer both concurrently and assert
    neither is ever lost."""
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
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
                    execution_profile_id="default", provider_id="local-openai", model_id="gpt-4o",
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


@pytest.mark.no_parallel
def test_cross_process_attempt_appends_do_not_lose_updates(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    request_id = record["request-id"]
    context = multiprocessing.get_context("spawn")
    count = 12
    processes = [
        context.Process(
            target=functools.partial(
                store.append_attempt,
                tmp_path,
                request_id,
                execution_profile_id="default",
                provider_id="local-openai",
                model_id=f"model-{index}",
                state="failed",
            ),
        )
        for index in range(count)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)

    assert [process.exitcode for process in processes] == [0] * count
    final = store.read_record(tmp_path, request_id)
    assert len(final["attempts"]) == count
    assert final["revision"] == count


def test_attempt_identity_rejects_stale_worker_terminal_write(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    running = store.start_attempt(tmp_path, record["request-id"], "worker-current")

    with pytest.raises(AudiaGenticError, match="CON-AGW-072"):
        store.transition_record(
            tmp_path,
            record["request-id"],
            "completed",
            expected_worker_id="worker-stale",
            expected_attempt_epoch=running["attempt-epoch"],
        )

    current = store.read_record(tmp_path, record["request-id"])
    assert current["state"] == "running"
    assert current["worker-id"] == "worker-current"
    assert current["attempt-epoch"] == 1


def test_append_attempt_does_not_change_state(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    updated = store.append_attempt(
        tmp_path, record["request-id"],
        execution_profile_id="default", provider_id="local-openai", model_id="gpt-4o",
        state="running", started_at="2026-01-01T00:00:00Z",
    )
    assert updated["state"] == "queued"
    assert len(updated["attempts"]) == 1
    assert updated["attempts"][0]["execution-profile-id"] == "default"
    timeline = load_ndjson(gateway_timeline_path(tmp_path, record["request-id"]))
    assert timeline[-1]["event"] == "attempt.recorded"
    assert timeline[-1]["attributes"]["attempt-state"] == "running"
    assert timeline[-1]["attributes"]["attempt-count"] == 1


def test_append_attempt_accepts_cancelled_state(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)

    updated = store.append_attempt(
        tmp_path, record["request-id"],
        execution_profile_id="default", provider_id="opencode", model_id="m1",
        state="cancelled", started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:00:01Z",
    )

    assert updated["attempts"][0]["state"] == "cancelled"


def test_terminal_states() -> None:
    assert store.TERMINAL_STATES == {"completed", "failed", "cancelled", "rejected", "interrupted"}


def test_read_migrates_v1_record_under_request_lock(tmp_path: Path) -> None:
    legacy = store.build_record(execution_profile_id="default", prompt_body="secret")
    store.write_record(tmp_path, legacy)
    legacy["contract-version"] = "v1"
    legacy.pop("dispatch-owner-epoch")
    legacy.pop("dispatch-claimed-at")
    legacy.pop("recovery")
    path = gateway_request_path(tmp_path, legacy["request-id"])
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["contract-version"] = "v1"
    raw.pop("dispatch-owner-epoch")
    raw.pop("dispatch-claimed-at")
    raw.pop("recovery")
    atomic_write_json(path, raw)

    migrated = store.read_record(tmp_path, legacy["request-id"])

    assert migrated["contract-version"] == "v5"
    assert migrated["dispatch-owner-epoch"] is None
    assert migrated["recovery"] is None
    assert migrated["resolved-source-id"] is None
    assert migrated["resolved-capacity-generation"] is None
    assert migrated["activity-sequence"] == 0
    assert migrated["last-activity-at"] is None
    assert json.loads(path.read_text(encoding="utf-8"))["contract-version"] == "v5"
    assert load_ndjson(gateway_timeline_path(tmp_path, legacy["request-id"]))[-1]["event"] == "record.migrated"


def test_read_repairs_partial_v4_activity_cutover(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    path = gateway_request_path(tmp_path, record["request-id"])
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["contract-version"] = "v4"
    for field in ("last-activity-at", "activity-sequence", "activity-source", "activity-lease-expires-at"):
        raw.pop(field, None)
    atomic_write_json(path, raw)
    repaired = store.read_record(tmp_path, record["request-id"])
    assert repaired["contract-version"] == "v5"
    assert repaired["activity-sequence"] == 0
    assert repaired["activity-source"] is None


def test_bind_and_start_owned_attempt_persists_placement_atomically(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0
    )

    running = store.bind_and_start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        worker_id="worker-a",
        expected_revision=claimed["revision"],
        resolved_source_id="gpu-a-chatgpt",
        resolved_model_id="chatgpt",
        resolved_capacity_generation="capacity-7",
    )

    assert running["state"] == "running"
    assert running["resolved-source-id"] == "gpu-a-chatgpt"
    assert running["resolved-model-id"] == "chatgpt"
    assert running["resolved-capacity-generation"] == "capacity-7"
    persisted = store.read_record(tmp_path, record["request-id"])
    assert persisted["resolved-source-id"] == "gpu-a-chatgpt"
    assert persisted["resolved-model-id"] == "chatgpt"
    timeline = load_ndjson(gateway_timeline_path(tmp_path, record["request-id"]))
    assert timeline[-1]["event"] == "dispatch.bound-and-started"


def test_bind_and_start_owned_attempt_fence_failure_writes_no_binding(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0
    )

    with pytest.raises(AudiaGenticError, match="CON-AGW-071"):
        store.bind_and_start_owned_attempt(
            tmp_path,
            record["request-id"],
            owner_epoch="service-a",
            worker_id="worker-a",
            expected_revision=claimed["revision"] + 1,
            resolved_source_id="gpu-a-chatgpt",
            resolved_model_id="chatgpt",
        )

    persisted = store.read_record(tmp_path, record["request-id"])
    assert persisted["state"] == "queued"
    assert persisted["resolved-source-id"] is None
    assert persisted["resolved-model-id"] is None


def test_owned_activity_renewal_persists_gateway_receipt_and_rejects_replay(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0
    )
    running = store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        worker_id="worker-a",
        expected_revision=claimed["revision"],
    )
    renewed = store.renew_owned_activity(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        worker_id="worker-a",
        attempt_epoch=running["attempt-epoch"],
        activity_seq=1,
        activity_source="worker-heartbeat",
        activity_lease_seconds=30,
    )
    assert renewed["activity-sequence"] == 1
    assert renewed["activity-source"] == "worker-heartbeat"
    assert renewed["last-activity-at"] is not None
    assert renewed["activity-lease-expires-at"] is not None
    assert renewed["watchdog-state"] == "active"
    assert renewed["watchdog-reason"] == "verified-activity-renewed"
    replay = store.renew_owned_activity(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        worker_id="worker-a",
        attempt_epoch=running["attempt-epoch"],
        activity_seq=1,
        activity_source="worker-heartbeat",
        activity_lease_seconds=30,
    )
    assert replay["revision"] == renewed["revision"]
    assert replay["last-activity-at"] == renewed["last-activity-at"]


@pytest.mark.parametrize("activity_source", ["provider-progress", "acp-progress", "mcp-a2a-progress"])
def test_provider_neutral_activity_source_renews_fenced_lease(tmp_path: Path, activity_source: str) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0)
    running = store.start_owned_attempt(tmp_path, record["request-id"], owner_epoch="service-a", worker_id="worker-a", expected_revision=claimed["revision"])
    renewed = store.renew_owned_activity(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        worker_id="worker-a",
        attempt_epoch=running["attempt-epoch"],
        activity_seq=1,
        activity_source=activity_source,
        activity_lease_seconds=300,
    )
    assert renewed["activity-source"] == activity_source
    assert renewed["watchdog-state"] == "active"


def test_activity_watchdog_state_survives_store_reload_nonterminal(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0)
    running = store.start_owned_attempt(tmp_path, record["request-id"], owner_epoch="service-a", worker_id="worker-a", expected_revision=claimed["revision"])
    renewed = store.renew_owned_activity(
        tmp_path, record["request-id"], owner_epoch="service-a", worker_id="worker-a",
        attempt_epoch=running["attempt-epoch"], activity_seq=7,
        activity_source="provider-progress", activity_lease_seconds=300,
    )
    reloaded = store.read_record(tmp_path, record["request-id"])
    assert reloaded["state"] == "running"
    assert reloaded["activity-sequence"] == renewed["activity-sequence"] == 7
    assert reloaded["watchdog-state"] == "active"
    assert reloaded["watchdog-reason"] == "verified-activity-renewed"


def test_owned_activity_renewal_rejects_wrong_attempt_fence(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0
    )
    running = store.start_owned_attempt(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        worker_id="worker-a",
        expected_revision=claimed["revision"],
    )
    with pytest.raises(AudiaGenticError, match="CON-AGW-073"):
        store.renew_owned_activity(
            tmp_path,
            record["request-id"],
            owner_epoch="service-a",
            worker_id="worker-a",
            attempt_epoch=running["attempt-epoch"] + 1,
            activity_seq=1,
            activity_source="worker-heartbeat",
            activity_lease_seconds=30,
        )


def test_expired_activity_only_marks_diagnostic_intervention(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0)
    running = store.start_owned_attempt(tmp_path, record["request-id"], owner_epoch="service-a", worker_id="worker-a", expected_revision=claimed["revision"])
    expired = dict(running)
    expired["activity-lease-expires-at"] = "2000-01-01T00:00:00Z"
    store.write_record(tmp_path, expired)

    diagnosed = store.mark_watchdog_intervention_if_expired(
        tmp_path,
        record["request-id"],
        owner_epoch="service-a",
        worker_id="worker-a",
        attempt_epoch=running["attempt-epoch"],
    )

    assert diagnosed["state"] == "running"
    assert diagnosed["watchdog-state"] == "intervention"
    assert diagnosed["watchdog-reason"] == "activity-lease-expired-diagnostic"


def test_owned_dispatch_fences_reject_stale_owner_worker_and_attempt(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0
    )
    running = store.start_owned_attempt(
        tmp_path, record["request-id"], owner_epoch="service-a", worker_id="worker-a",
        expected_revision=claimed["revision"],
    )

    with pytest.raises(AudiaGenticError, match="CON-AGW-083"):
        store.transition_owned_terminal(
            tmp_path, record["request-id"], "completed", owner_epoch="service-b",
            worker_id="worker-a", attempt_epoch=running["attempt-epoch"],
        )
    with pytest.raises(AudiaGenticError, match="CON-AGW-072"):
        store.transition_owned_terminal(
            tmp_path, record["request-id"], "completed", owner_epoch="service-a",
            worker_id="worker-b", attempt_epoch=running["attempt-epoch"],
        )
    with pytest.raises(AudiaGenticError, match="CON-AGW-073"):
        store.transition_owned_terminal(
            tmp_path, record["request-id"], "completed", owner_epoch="service-a",
            worker_id="worker-a", attempt_epoch=running["attempt-epoch"] + 1,
        )

    terminal = store.transition_owned_terminal(
        tmp_path, record["request-id"], "interrupted", owner_epoch="service-a",
        worker_id="worker-a", attempt_epoch=running["attempt-epoch"],
        updates={"recovery": {"reason": "service-restart", "outcome": "resubmit-required"}},
    )
    assert terminal["state"] == "interrupted"


def test_owned_mutations_require_a_complete_owner_identity(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    running = store.start_attempt(tmp_path, record["request-id"], "worker-current")

    with pytest.raises(AudiaGenticError, match="VAL-AGW-085"):
        store.append_owned_attempt(
            tmp_path, record["request-id"],
            owner_epoch="", worker_id="worker-current", attempt_epoch=running["attempt-epoch"],
            execution_profile_id="default", provider_id="local-openai", model_id="gpt-4o", state="failed",
        )
    with pytest.raises(AudiaGenticError, match="VAL-AGW-085"):
        store.transition_owned_terminal(
            tmp_path, record["request-id"], "failed",
            owner_epoch=None,  # type: ignore[arg-type]
            worker_id="worker-current", attempt_epoch=running["attempt-epoch"],
        )


def test_recovery_record_is_a_strict_safe_projection(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(
        tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0
    )
    running = store.start_owned_attempt(
        tmp_path, record["request-id"], owner_epoch="service-a", worker_id="worker-a",
        expected_revision=claimed["revision"],
    )

    with pytest.raises(AudiaGenticError, match="VAL-AGW-004"):
        store.transition_owned_terminal(
            tmp_path, record["request-id"], "interrupted",
            owner_epoch="service-a", worker_id="worker-a", attempt_epoch=running["attempt-epoch"],
            updates={"recovery": {"reason": "service-restart", "outcome": "resubmit-required", "secret": "nope"}},
        )

    terminal = store.transition_owned_terminal(
        tmp_path, record["request-id"], "interrupted",
        owner_epoch="service-a", worker_id="worker-a", attempt_epoch=running["attempt-epoch"],
        updates={"recovery": {"reason": "service-restart", "outcome": "resubmit-required"}},
    )
    status = store.read_public_status(tmp_path, record["request-id"])
    assert terminal["recovery"] == {"reason": "service-restart", "outcome": "resubmit-required"}
    assert status["recovery"] == terminal["recovery"]


def test_public_status_latest_transition_excludes_timeline_attributes(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    store.record_gateway_timeline(
        tmp_path,
        record["request-id"],
        "operator.checked",
        state="queued",
        attributes={"raw-secret": "must-not-be-projected", "context-fingerprint": "also-private"},
    )

    status = store.read_public_status(tmp_path, record["request-id"])

    assert status["latest-transition"] is not None
    assert status["latest-transition"]["event"] == "operator.checked"
    assert status["latest-transition"]["state"] == "queued"
    assert set(status["latest-transition"]) == {"event", "state", "timestamp"}
    assert "raw-secret" not in status["latest-transition"]
    assert "context-fingerprint" not in status["latest-transition"]


def test_public_status_projection_excludes_submission_secrets() -> None:
    record = store.build_record(
        execution_profile_id="default", prompt_body="secret", prompt_digest="digest",
        context_fingerprint="fingerprint", idempotency_key="key", metadata={"subject": "private"},
    )
    status = store.project_public_status(record)
    assert "prompt-body" not in status
    assert "prompt-digest" not in status
    assert "context-fingerprint" not in status
    assert "idempotency-key" not in status
    # metadata is sanitized and returned to the caller — it is not a secret
    assert "metadata" in status


# ── SH21 RV769: private worker diagnostic evidence ───────────────────────

def test_sh21_rv769_int_agw_076_persists_private_worker_evidence(
    tmp_path: Path,
) -> None:
    """INT-AGW-076 error with worker-diagnostic in details persists a bounded
    redacted private evidence field. The public error remains generic/redacted.

    Regression for the gap where req_0764e2e390f644ca failed INT-AGW-076 yet
    its durable record/timeline held only a generic public error despite the
    initial worker diagnostics patch.

    The worker-diagnostic is already redacted by AudiaGenticError at construction
    (secrets in details are replaced with [REDACTED]). The private evidence field
    carries this already-redacted diagnostic — operators see the structure but
    secrets are stripped at the error-envelope boundary.
    """
    SENSITIVE_STRING = "Bearer sk-proj-abcdef1234567890"
    worker_diagnostic = (
        f"WORKER-EXCEPTION: ValueError: provider failed with secret={SENSITIVE_STRING}\n"
        f"Traceback (most recent call last):\n"
        f"  File \"agents_gateway_worker_host.py\", line 120, in main\n"
        f"    raise ValueError(\"provider failed\")\n"
    )

    err = AudiaGenticError(
        code="INT-AGW-076",
        kind="agents",
        message="isolated provider worker failed unexpectedly",
        details={"worker-diagnostic": worker_diagnostic},
    )

    # AudiaGenticError redacts secrets in details; the diagnostic becomes [REDACTED]
    assert err.details["worker-diagnostic"] == "[REDACTED]"  # type: ignore[index]

    record = store.build_record(execution_profile_id="default", prompt_body="do the thing")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    updated = store.transition_record(  # type: ignore[assignment]
        tmp_path, record["request-id"], "failed",
        updates={"error": err},
    )

    # ── Public error must remain generic/redacted (only code/message/kind) ──
    assert updated["error"] == {
        "code": "INT-AGW-076",
        "message": "isolated provider worker failed unexpectedly",
        "kind": "agents",
    }
    assert "worker-diagnostic" not in updated["error"]
    assert SENSITIVE_STRING not in str(updated["error"])

    # ── Private worker-evidence must contain the redacted diagnostic ─────
    assert updated.get("worker-evidence") is not None
    evidence = updated["worker-evidence"]
    assert "error-type" in evidence
    # error-type is type(error).__name__; AudiaGenticError is aliased as _Error
    assert evidence["error-type"] in ("AudiaGenticError", "_Error")
    assert "worker-diagnostic" in evidence
    # The diagnostic was redacted by AudiaGenticError at construction time,
    # so the private field carries the already-redacted value.
    assert evidence["worker-diagnostic"] == "[REDACTED]"
    # Secret must NOT be present anywhere in the persisted record
    assert SENSITIVE_STRING not in str(updated)

    # ── Public status must NOT expose worker-evidence ──────────────────
    status = store.project_public_status(updated)
    assert "worker-evidence" not in status
    assert SENSITIVE_STRING not in str(status)


def test_sh21_rv769_safe_worker_diagnostic_survives_in_evidence(
    tmp_path: Path,
) -> None:
    """A worker diagnostic WITHOUT secrets survives intact in private evidence
    and is NOT exposed in public error or public status."""
    safe_diagnostic = (
        "WORKER-EXCEPTION: ValueError: provider failed unexpectedly\n"
        "Traceback (most recent call last):\n"
        "  File \"agents_gateway_worker_host.py\", line 120, in main\n"
        "    raise ValueError(\"provider failed\")\n"
    )

    err = AudiaGenticError(
        code="INT-AGW-076",
        kind="agents",
        message="isolated provider worker failed unexpectedly",
        details={"worker-diagnostic": safe_diagnostic},
    )
    # Safe diagnostic is NOT redacted (no secret patterns)
    assert err.details["worker-diagnostic"] == safe_diagnostic  # type: ignore[index]

    record = store.build_record(execution_profile_id="default", prompt_body="do the thing")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    updated = store.transition_record(  # type: ignore[assignment]
        tmp_path, record["request-id"], "failed",
        updates={"error": err},
    )

    # Public error is redacted (no diagnostics)
    assert updated["error"] == {
        "code": "INT-AGW-076",
        "message": "isolated provider worker failed unexpectedly",
        "kind": "agents",
    }

    # Private evidence contains the safe diagnostic intact
    assert updated.get("worker-evidence") is not None
    evidence = updated["worker-evidence"]
    # error-type is type(error).__name__; AudiaGenticError is aliased as _Error
    assert evidence["error-type"] in ("AudiaGenticError", "_Error")
    assert evidence["worker-diagnostic"] == safe_diagnostic
    assert "Traceback" in evidence["worker-diagnostic"]
    assert "ValueError" in evidence["worker-diagnostic"]

    # Public status does NOT expose worker-evidence
    status = store.project_public_status(updated)
    assert "worker-evidence" not in status
    assert "Traceback" not in str(status)


def test_sh21_rv769_non_076_errors_no_worker_evidence(tmp_path: Path) -> None:
    """Non-INT-AGW-076 errors must NOT create a worker-evidence field."""
    err = AudiaGenticError(
        code="EXT-CLAUDE-001",
        kind="providers",
        message="claude execution failed",
        details={"stdout": "some output"},
    )

    record = store.build_record(execution_profile_id="default", prompt_body="do the thing")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    updated = store.transition_record(
        tmp_path, record["request-id"], "failed",
        updates={"error": err},
    )

    assert updated["error"] == {
        "code": "EXT-CLAUDE-001",
        "message": "claude execution failed",
        "kind": "providers",
    }
    assert updated.get("worker-evidence") is None


def test_sh21_rv769_int_agw_076_without_diagnostic_no_evidence(
    tmp_path: Path,
) -> None:
    """INT-AGW-076 error WITHOUT worker-diagnostic in details must NOT
    create a worker-evidence field."""
    err = AudiaGenticError(
        code="INT-AGW-076",
        kind="agents",
        message="isolated provider worker failed unexpectedly",
        details={"worker-id": "worker-test"},
    )

    record = store.build_record(execution_profile_id="default", prompt_body="do the thing")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    updated = store.transition_record(
        tmp_path, record["request-id"], "failed",
        updates={"error": err},
    )

    assert updated["error"] == {
        "code": "INT-AGW-076",
        "message": "isolated provider worker failed unexpectedly",
        "kind": "agents",
    }
    assert updated.get("worker-evidence") is None


def test_sh21_rv769_to_agw_076_no_worker_evidence(tmp_path: Path) -> None:
    """TO-AGW-076 (timeout) must NOT leak worker diagnostics."""
    err = AudiaGenticError(
        code="TO-AGW-076",
        kind="agents",
        message="isolated provider worker exceeded its execution timeout",
        details={"worker-id": "worker-test"},
    )

    record = store.build_record(execution_profile_id="default", prompt_body="do the thing")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    updated = store.transition_record(
        tmp_path, record["request-id"], "failed",
        updates={"error": err},
    )

    assert updated["error"] == {
        "code": "TO-AGW-076",
        "message": "isolated provider worker exceeded its execution timeout",
        "kind": "agents",
    }
    assert updated.get("worker-evidence") is None


def test_sh21_rv769_worker_evidence_is_bounded(tmp_path: Path) -> None:
    """Worker diagnostic evidence is bounded to 2 KB."""
    _MAX = 2 * 1024
    oversized_diagnostic = "x" * (_MAX + 500)

    err = AudiaGenticError(
        code="INT-AGW-076",
        kind="agents",
        message="isolated provider worker failed unexpectedly",
        details={"worker-diagnostic": oversized_diagnostic},
    )

    record = store.build_record(execution_profile_id="default", prompt_body="do the thing")
    store.write_record(tmp_path, record)
    store.transition_record(tmp_path, record["request-id"], "running")
    updated = store.transition_record(
        tmp_path, record["request-id"], "failed",
        updates={"error": err},
    )

    assert updated.get("worker-evidence") is not None
    evidence = updated["worker-evidence"]
    diag = evidence["worker-diagnostic"]
    # Must be truncated to 2 KB + "\n<truncated>"
    assert len(diag) <= _MAX + len("\n<truncated>")
    assert diag.endswith("\n<truncated>")


def test_owned_terminal_persists_watchdog_classification(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0)
    running = store.start_owned_attempt(tmp_path, record["request-id"], owner_epoch="service-a", worker_id="worker-a", expected_revision=claimed["revision"])
    terminal = store.transition_owned_terminal(
        tmp_path,
        record["request-id"],
        "failed",
        owner_epoch="service-a",
        worker_id="worker-a",
        attempt_epoch=running["attempt-epoch"],
        updates={"error": {"code": "TO-AGW-076", "details": {"watchdog-classification": "verified-stall"}}},
    )
    assert terminal["terminal-classification"] == "verified-stall"


def test_owned_terminal_persists_absolute_safety_ceiling_classification(tmp_path: Path) -> None:
    record = store.build_record(execution_profile_id="default", prompt_body="hello")
    store.write_record(tmp_path, record)
    claimed = store.claim_dispatch(tmp_path, record["request-id"], owner_epoch="service-a", expected_revision=0)
    running = store.start_owned_attempt(tmp_path, record["request-id"], owner_epoch="service-a", worker_id="worker-a", expected_revision=claimed["revision"])
    terminal = store.transition_owned_terminal(
        tmp_path,
        record["request-id"],
        "failed",
        owner_epoch="service-a",
        worker_id="worker-a",
        attempt_epoch=running["attempt-epoch"],
        updates={"error": {"code": "TO-AGW-077", "details": {"watchdog-classification": "absolute-safety-ceiling"}}},
    )
    assert terminal["terminal-classification"] == "absolute-safety-ceiling"
