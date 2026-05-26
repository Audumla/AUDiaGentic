from __future__ import annotations

import json
from pathlib import Path

from audiagentic.foundation.event.envelope import EventEnvelope
from audiagentic.foundation.event.log import StructuredLog


def _records(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_structured_log_writes_otel_style_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "logs" / "workflow.jsonl"
    log = StructuredLog(path)
    log.emit(
        body="workflow.propagation.skipped",
        severity_text="INFO",
        attributes={"event.name": "workflow.propagation.skipped"},
    )

    record = _records(path)[0]
    assert record["timestamp"]
    assert record["observed_timestamp"]
    assert record["severity_text"] == "INFO"
    assert record["body"] == "workflow.propagation.skipped"
    assert record["attributes"]["event.name"] == "workflow.propagation.skipped"


def test_structured_log_none_path_is_noop() -> None:
    StructuredLog(None).emit(body="noop")


def test_structured_log_emits_canonical_event_record(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    log = StructuredLog(path)
    log.emit_event(
        EventEnvelope(
            type="planning.item.state.changed",
            payload={"id": "task-1", "new_state": "done"},
            metadata={"subject": {"kind": "task", "id": "task-1"}},
            source_component="planning",
        )
    )

    record = _records(path)[0]
    assert record["timestamp"]
    assert record["body"] == "planning.item.state.changed"
    assert record["attributes"]["event.name"] == "planning.item.state.changed"
    assert record["attributes"]["payload"]["id"] == "task-1"
    assert record["attributes"]["subject"]["id"] == "task-1"
