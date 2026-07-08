from __future__ import annotations

from audiagentic.foundation.io import load_ndjson
from audiagentic.foundation.observability import record_timeline_event


def test_record_timeline_event_appends_jsonl(tmp_path):
    path = tmp_path / "timeline.ndjson"

    record_timeline_event(
        path,
        component="test-component",
        resource_kind="thing",
        resource_id="T01",
        event="created",
        state="ready",
        attributes={"answer": 42},
    )

    entries = load_ndjson(path)
    assert len(entries) == 1
    assert entries[0]["component"] == "test-component"
    assert entries[0]["resource-kind"] == "thing"
    assert entries[0]["resource-id"] == "T01"
    assert entries[0]["correlation-id"] is None
    assert entries[0]["event"] == "created"
    assert entries[0]["state"] == "ready"
    assert entries[0]["attributes"] == {"answer": 42}


def test_record_timeline_event_uses_correlation_id_attribute(tmp_path):
    path = tmp_path / "timeline.ndjson"

    record_timeline_event(
        path,
        component="test-component",
        resource_kind="thing",
        resource_id="T01",
        event="created",
        attributes={"correlation_id": "corr-123"},
    )

    entries = load_ndjson(path)
    assert entries[0]["correlation-id"] == "corr-123"
