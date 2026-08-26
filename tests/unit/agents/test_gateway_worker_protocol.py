from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from audiagentic.components.agents.contracts.worker_protocol import (
    WORKER_PROTOCOL_VERSION,
    WorkerActivityEnvelope,
    WorkerErrorEnvelope,
    WorkerExecuteEnvelope,
    WorkerExecutionIdentity,
    WorkerHandshakeEnvelope,
    WorkerProcessEvidence,
    WorkerResultEnvelope,
    decode_worker_message,
    encode_worker_message,
)
from audiagentic.components.agents.gateway.queue.worker_host import (
    _provider_activity_path,
    _watch_provider_activity,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

FINGERPRINT = "a" * 64


def _identity(root: Path, **overrides: object) -> WorkerExecutionIdentity:
    values: dict[str, object] = {
        "worker_id": "worker-1",
        "attempt_epoch": 2,
        "manifest_id": "manifest-1",
        "context_fingerprint": FINGERPRINT,
        "project_root": str(root.resolve()),
        "component_profile": "reviewer",
        "provider_isolation_tier": "full-isolation",
    }
    values.update(overrides)
    return WorkerExecutionIdentity(**values)  # type: ignore[arg-type]


def _process() -> WorkerProcessEvidence:
    return WorkerProcessEvidence(
        pid=27182,
        process_creation_identity="proc-start:8675309",
        working_directory=str(Path.cwd().resolve()),
    )


def _execution_request(root: Path, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "project-root": str(root.resolve()),
        "provider-id": "fixture-provider",
        "model-id": "fixture-model",
        "model-alias": None,
        "packet-data": {"prompt-body": "runtime-only canary", "metadata": {"case": "two-project"}},
        "worker-id": "worker-1",
        "attempt-epoch": 2,
        "provider-isolation-tier": "full-isolation",
    }
    values.update(overrides)
    return values


def _execution_result(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "provider-id": "fixture-provider",
        "model-id": "fixture-model",
        "worker-id": "worker-1",
        "attempt-epoch": 2,
        "result-data": {"text": "runtime-only output"},
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "message_factory, expected_type",
    [
        (
            lambda root: WorkerExecuteEnvelope(_identity(root), _execution_request(root)),
            WorkerExecuteEnvelope,
        ),
        (
            lambda root: WorkerHandshakeEnvelope(_identity(root), _process()),
            WorkerHandshakeEnvelope,
        ),
        (
            lambda root: WorkerActivityEnvelope(_identity(root), _process(), 1, "worker-heartbeat"),
            WorkerActivityEnvelope,
        ),
        (
            lambda root: WorkerResultEnvelope(_identity(root), _process(), _execution_result()),
            WorkerResultEnvelope,
        ),
        (
            lambda root: WorkerErrorEnvelope(
                _identity(root),
                _process(),
                "EXT-PEXE-001",
                "providers",
                "provider execution failed",
            ),
            WorkerErrorEnvelope,
        ),
    ],
)
def test_worker_messages_round_trip_as_versioned_json(
    tmp_path: Path, message_factory: object, expected_type: type[object]
) -> None:
    message = message_factory(tmp_path)  # type: ignore[operator]

    encoded = encode_worker_message(message)
    decoded = decode_worker_message(encoded)

    assert isinstance(decoded, expected_type)
    assert decoded == message
    assert decoded.to_mapping()["protocol-version"] == WORKER_PROTOCOL_VERSION


def test_handshake_carries_complete_process_and_context_evidence(tmp_path: Path) -> None:
    mapping = WorkerHandshakeEnvelope(_identity(tmp_path), _process()).to_mapping()

    assert mapping == {
        "protocol-version": "gateway-worker-v1",
        "message-type": "handshake",
        "worker-id": "worker-1",
        "attempt-epoch": 2,
        "manifest-id": "manifest-1",
        "context-fingerprint": FINGERPRINT,
        "project-root": str(tmp_path.resolve()),
        "component-profile": "reviewer",
        "accepted-isolation-tier": "full-isolation",
        "pid": 27182,
        "process-creation-identity": "proc-start:8675309",
        "working-directory": str(Path.cwd().resolve()),
    }


def test_worker_relays_normalized_provider_events_as_bounded_activity(tmp_path: Path) -> None:
    request = _execution_request(tmp_path)
    request["packet-data"] = {"request-id": "req_activity", "job-id": "req_activity"}
    path = _provider_activity_path(request)
    assert path == (tmp_path / ".audiagentic" / "runtime" / "jobs" / "req_activity" / "events.ndjson").resolve()

    path.parent.mkdir(parents=True)
    stop = threading.Event()
    observed: list[str] = []
    thread = threading.Thread(target=_watch_provider_activity, args=(path, stop, observed.append), daemon=True)
    thread.start()
    path.write_text(json.dumps({"event-kind": "task-progress", "message": "redacted"}) + "\n", encoding="utf-8")
    deadline = time.monotonic() + 2
    while not observed and time.monotonic() < deadline:
        time.sleep(0.02)
    stop.set()
    thread.join(timeout=1)

    assert observed == ["provider-progress"]


def test_runtime_payloads_are_excluded_from_repr(tmp_path: Path) -> None:
    execute = WorkerExecuteEnvelope(_identity(tmp_path), _execution_request(tmp_path))
    result = WorkerResultEnvelope(_identity(tmp_path), _process(), _execution_result())

    assert "runtime-only canary" not in repr(execute)
    assert "runtime-only output" not in repr(result)


@pytest.mark.parametrize("forbidden", ["env", "configuration", "credentials", "secret"])
def test_execute_rejects_runtime_material_side_channels(tmp_path: Path, forbidden: str) -> None:
    request = _execution_request(tmp_path)
    request["packet-data"] = {"prompt-body": "safe", "nested": {forbidden: {"x": "y"}}}

    with pytest.raises(AudiaGenticError, match="VAL-AGW-075"):
        WorkerExecuteEnvelope(_identity(tmp_path), request)


def test_execute_rejects_unknown_provider_request_fields(tmp_path: Path) -> None:
    request = _execution_request(tmp_path)
    request["provider-config"] = {"unsafe": True}

    with pytest.raises(AudiaGenticError, match="VAL-AGW-074"):
        WorkerExecuteEnvelope(_identity(tmp_path), request)


@pytest.mark.parametrize(
    "overrides",
    [
        {"worker-id": "different"},
        {"attempt-epoch": 3},
        {"project-root": "C:\\different"},
        {"provider-isolation-tier": "partial-isolation"},
    ],
)
def test_execute_rejects_outer_inner_identity_mismatch(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    with pytest.raises(AudiaGenticError, match="CON-AGW-074"):
        WorkerExecuteEnvelope(_identity(tmp_path), _execution_request(tmp_path, **overrides))


def test_result_rejects_stale_attempt_identity(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError, match="CON-AGW-074"):
        WorkerResultEnvelope(
            _identity(tmp_path), _process(), _execution_result(**{"attempt-epoch": 1})
        )


@pytest.mark.parametrize("sequence, source", [(0, "worker-heartbeat"), (1, "bad source"), (True, "worker-heartbeat")])
def test_activity_envelope_requires_bounded_monotonic_safe_fields(
    tmp_path: Path, sequence: object, source: str
) -> None:
    with pytest.raises(AudiaGenticError, match="VAL-AGW-074"):
        WorkerActivityEnvelope(_identity(tmp_path), _process(), sequence, source)  # type: ignore[arg-type]


def test_decoder_rejects_unknown_fields_and_versions(tmp_path: Path) -> None:
    mapping = WorkerHandshakeEnvelope(_identity(tmp_path), _process()).to_mapping()
    mapping["env"] = {"SHOULD": "NOT TRAVEL"}
    with pytest.raises(AudiaGenticError, match="VAL-AGW-074"):
        decode_worker_message(__import__("json").dumps(mapping))

    mapping.pop("env")
    mapping["protocol-version"] = "gateway-worker-v2"
    with pytest.raises(AudiaGenticError, match="VER-AGW-001"):
        decode_worker_message(__import__("json").dumps(mapping))


@pytest.mark.parametrize(
    "overrides",
    [
        {"attempt_epoch": 0},
        {"context_fingerprint": "not-a-digest"},
        {"component_profile": "../escape"},
        {"provider_isolation_tier": "provider-name-heuristic"},
    ],
)
def test_identity_rejects_invalid_worker_context(
    tmp_path: Path, overrides: dict[str, object]
) -> None:
    with pytest.raises(AudiaGenticError, match="VAL-AGW-074"):
        _identity(tmp_path, **overrides)


def test_identity_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    noncanonical = tmp_path / "folder" / ".."

    with pytest.raises(AudiaGenticError, match="VAL-AGW-074"):
        _identity(tmp_path, project_root=str(noncanonical))


@pytest.mark.parametrize(
    "message",
    [
        "Traceback (most recent call last):\nraw stack",
        "provider rejected bearer abcdefghijklmnopqrstuvwxyz",
        "x" * 513,
    ],
)
def test_error_envelope_rejects_raw_or_secret_bearing_messages(
    tmp_path: Path, message: str
) -> None:
    with pytest.raises(AudiaGenticError, match="VAL-AGW-075"):
        WorkerErrorEnvelope(_identity(tmp_path), _process(), "EXT-PEXE-001", "providers", message)
