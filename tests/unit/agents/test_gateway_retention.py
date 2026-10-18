from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.agents.agents_paths import gateway_request_dir, gateway_timeline_path
from audiagentic.components.agents.gateway.operations.retention_policy import (
    DEFAULT_CONSOLE_TRACE_MAX_BYTES,
    DEFAULT_OBSERVATION_MAX_BYTES,
    DEFAULT_RECOVERY_MAX_BYTES,
    DEFAULT_REQUEST_HISTORY_LIMIT,
    DEFAULT_TIMELINE_MAX_BYTES,
    load_retention_policy,
)
from audiagentic.components.agents.gateway.retention import (
    compact_indexed_ndjson,
    enforce_request_retention,
)
from audiagentic.components.agents.gateway.session.console_trace import GatewayConsoleTrace


def test_retention_policy_defaults_and_machine_overrides(tmp_path: Path, monkeypatch) -> None:
    policy_path = tmp_path / "missing-policy.json"
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(policy_path))
    default = load_retention_policy()
    assert default.request_history_limit == DEFAULT_REQUEST_HISTORY_LIMIT
    assert default.timeline_max_bytes == DEFAULT_TIMELINE_MAX_BYTES
    assert default.observation_max_bytes == DEFAULT_OBSERVATION_MAX_BYTES
    assert default.recovery_max_bytes == DEFAULT_RECOVERY_MAX_BYTES
    assert default.console_trace_max_bytes == DEFAULT_CONSOLE_TRACE_MAX_BYTES

    policy_path.write_text(
        json.dumps(
            {
                "policy-id": "ops",
                "request-history-limit": 7,
                "timeline-max-bytes": 700,
                "observation-max-bytes": 800,
                "recovery-max-bytes": 900,
                "console-trace-max-bytes": 1000,
            }
        ),
        encoding="utf-8",
    )
    configured = load_retention_policy()
    assert configured.available is True
    assert configured.request_history_limit == 7
    assert configured.timeline_max_bytes == 700
    assert configured.observation_max_bytes == 800
    assert configured.recovery_max_bytes == 900
    assert configured.console_trace_max_bytes == 1000


def test_indexed_compaction_preserves_terminal_evidence_and_rebuilds_offsets(tmp_path: Path) -> None:
    journal = tmp_path / "timeline.ndjson"
    index = tmp_path / "timeline.index.ndjson"
    rows = [
        {"event": "old", "state": "running", "payload": "x" * 90},
        {"event": "terminal", "state": "completed", "payload": "evidence"},
        {"event": "latest", "state": "running", "payload": "tail"},
    ]
    journal.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    index.write_text("{}\n{}\n{}\n", encoding="utf-8")

    assert compact_indexed_ndjson(
        journal,
        index,
        max_bytes=240,
        preserve=lambda row: row.get("state") == "completed",
    )
    compacted = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
    assert [row["event"] for row in compacted] == ["terminal", "latest"]
    assert journal.stat().st_size <= 350

    offset = 0
    for line, metadata_line in zip(journal.read_bytes().splitlines(keepends=True), index.read_bytes().splitlines()):
        metadata = json.loads(metadata_line)
        assert metadata["offset"] == offset
        assert metadata["length"] == len(line)
        offset += len(line)


def test_rolling_retention_compacts_old_resolved_histories_without_deleting_directories(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_REQUEST_RETENTION_COUNT", "1")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_TIMELINE_MAX_BYTES", "500")
    request_ids = ["req_old", "req_middle", "req_new"]
    for index, request_id in enumerate(request_ids):
        request_dir = gateway_request_dir(tmp_path, request_id)
        request_dir.mkdir(parents=True)
        (request_dir / "record.json").write_text(
            json.dumps(
                {
                    "request-id": request_id,
                    "state": "completed",
                    "finished-at": f"2026-10-{10 + index:02d}T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        timeline = gateway_timeline_path(tmp_path, request_id)
        timeline.write_text(
            "".join(json.dumps({"event": f"event-{item}", "state": "running", "payload": "x" * 120}) + "\n" for item in range(8))
            + json.dumps({"event": "terminal", "state": "completed"}) + "\n",
            encoding="utf-8",
        )

    result = enforce_request_retention(tmp_path)

    assert result["limit"] == 1
    assert result["eligible"] == 3
    assert result["compacted"] >= 2
    assert all(gateway_request_dir(tmp_path, request_id).exists() for request_id in request_ids)
    assert all(gateway_request_dir(tmp_path, request_id).joinpath("record.json").exists() for request_id in request_ids)


def test_console_trace_rotates_one_bounded_backup(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE", "summary")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE_MAX_BYTES", "400")
    path = tmp_path / "console-trace.log"
    stream = path.open("a", encoding="utf-8", buffering=1)
    trace = GatewayConsoleTrace(stream=stream)
    for index in range(8):
        trace.session_opened(
            session_id=f"ses_{index}",
            provider_id="codex",
            model_id="model",
            execution_profile_id="profile",
            surface_id="surface",
            child_pid=index,
        )
    assert trace.stream is not None
    trace.stream.close()

    backup = path.with_name(path.name + ".1")
    assert backup.exists()
    assert path.stat().st_size <= 400
    assert backup.stat().st_size <= 400
