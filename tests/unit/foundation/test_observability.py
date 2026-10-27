from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from audiagentic.foundation.io import load_ndjson
from audiagentic.foundation.observability import (
    record_timeline_event,
    timeline,
    timeline_failure_count,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


@pytest.fixture(autouse=True)
def isolated_failure_count(monkeypatch):
    # Isolate process-local counters without adding production reset semantics.
    with timeline._timeline_failure_count_guard:
        monkeypatch.setattr(timeline, "_timeline_failure_count", 0)


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


def event(path, **changes):
    args = dict(component="test", resource_kind="thing", resource_id="T01", event="created")
    args.update(changes)
    return record_timeline_event(path, **args)


def fail_append(monkeypatch, path):
    original = Path.open

    def opened(candidate, mode="r", *args, **kwargs):
        if candidate == path and mode == "a":
            raise OSError("PRIVATE filesystem failure")
        return original(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)


def test_append_and_warning_failures_never_escape_and_warning_is_not_retried(tmp_path, monkeypatch):
    path = tmp_path / "PRIVATE" / "events.ndjson"
    fail_append(monkeypatch, path)
    counts_at_warning = []

    def broken_warning(*args, **kwargs):
        counts_at_warning.append(timeline_failure_count())
        raise RuntimeError("PRIVATE logger failure")

    warning = Mock(side_effect=broken_warning)
    monkeypatch.setattr(timeline.logger, "warning", warning)
    record = event(path, attributes={"output": "PRIVATE"}, timestamp="fixed-time")
    second = event(path, event="next")
    assert record["attributes"] == {"output": "PRIVATE"} and record["timestamp"] == "fixed-time"
    assert second["event"] == "next"
    assert timeline_failure_count() == 2
    assert counts_at_warning == [1] and warning.call_count == 1


def test_failure_warning_contains_only_fixed_message_no_private_fields_or_traceback(
    tmp_path, monkeypatch, caplog
):
    path = tmp_path / "PRIVATE-path" / "events.ndjson"
    fail_append(monkeypatch, path)
    with caplog.at_level(logging.WARNING, logger=timeline.logger.name):
        record = event(
            path,
            component="PRIVATE-component",
            resource_kind="PRIVATE-kind",
            resource_id="PRIVATE-resource",
            event="PRIVATE-event",
            state="PRIVATE-state",
            correlation_id="PRIVATE-correlation",
            attributes={"output": "PRIVATE-output"},
        )
    logs = [row for row in caplog.records if row.name == timeline.logger.name]
    assert len(logs) == 1
    warning = logs[0]
    assert warning.getMessage() == "Timeline recording failed; inspect timeline_failure_count"
    assert warning.args == () and warning.exc_info is None and warning.stack_info is None
    assert (
        not {"path", "component", "resource_kind", "resource_id", "event"} & warning.__dict__.keys()
    )
    assert "PRIVATE" not in repr(warning.__dict__)
    assert record["correlation-id"] == "PRIVATE-correlation"
    assert timeline_failure_count() == 1


@pytest.mark.parametrize("broken_sink", [False, True])
def test_concurrent_failures_count_exactly_and_warn_once(tmp_path, monkeypatch, broken_sink):
    path = tmp_path / "events.ndjson"
    fail_append(monkeypatch, path)
    counts_at_warning = []

    def warn(*args, **kwargs):
        counts_at_warning.append(timeline_failure_count())  # Also proves no counter-lock recursion.
        if broken_sink:
            raise RuntimeError("sink unavailable")

    warning = Mock(side_effect=warn)
    monkeypatch.setattr(timeline.logger, "warning", warning)
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda i: event(path, resource_id=f"T{i}"), range(40)))
    assert timeline_failure_count() == 40
    assert warning.call_count == 1 and len(counts_at_warning) == 1
    assert 1 <= counts_at_warning[0] <= 40
    assert {row["resource-id"] for row in records} == {f"T{i}" for i in range(40)}


def test_index_failure_counts_operation_without_retrying_successful_append(tmp_path, monkeypatch):
    path = tmp_path / "events.ndjson"
    index = path.with_suffix(".index.ndjson")
    original = Path.open
    appends = []

    def opened(candidate, mode="r", *args, **kwargs):
        if mode == "a" and candidate in (path, index):
            appends.append(candidate)
            if candidate == index:
                raise OSError("PRIVATE index failure after row append")
        return original(candidate, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    warning = Mock(side_effect=RuntimeError("sink unavailable"))
    monkeypatch.setattr(timeline.logger, "warning", warning)
    record = event(path)
    assert load_ndjson(path) == [record]
    first_size = path.stat().st_size  # Preserve existing platform newline behavior.
    assert appends == [path, index]  # No retry of a possibly completed append.
    assert timeline_failure_count() == 1 and warning.call_count == 1
    monkeypatch.setattr(Path, "open", original)
    second = event(path, event="next")
    assert load_ndjson(path) == [record, second]
    assert timeline_failure_count() == 1
    assert load_ndjson(index) == [
        {
            "offset": first_size,
            "length": len((json.dumps(second, sort_keys=True) + "\n").encode("utf-8")),
        }
    ]


def test_success_keeps_failure_count_unchanged_and_index_bytes_exact(tmp_path, monkeypatch):
    path = tmp_path / "timeline.ndjson"
    warning = Mock()
    monkeypatch.setattr(timeline.logger, "warning", warning)
    first = event(path)
    assert timeline_failure_count() == 0
    fail_append(monkeypatch, tmp_path / "failed.ndjson")
    event(tmp_path / "failed.ndjson")
    assert timeline_failure_count() == 1
    second = event(path, event="next")
    assert timeline_failure_count() == 1 and warning.call_count == 1
    assert load_ndjson(path) == [first, second]
    raw = path.read_bytes()
    for row, metadata in zip(
        [first, second], load_ndjson(path.with_suffix(".index.ndjson")), strict=True
    ):
        assert json.loads(raw[metadata["offset"] : metadata["offset"] + metadata["length"]]) == row


def test_managed_service_authoritative_mutations_survive_timeline_and_warning_failures(
    tmp_path, monkeypatch
):
    service = ManagedServiceStore(ServiceKey("timeline-test", "owner"), root=tmp_path)
    fail_append(monkeypatch, service.timeline_path)
    warning = Mock(side_effect=RuntimeError("PRIVATE sink failure"))
    monkeypatch.setattr(timeline.logger, "warning", warning)
    created = service.create(protocol_version="1", owner_epoch="epoch")
    assert service.read() == created
    assert created.state == "starting" and created.revision == 1
    updated = service.transition(
        "failed", expected_revision=created.revision, expected_epoch=created.owner_epoch
    )
    assert service.read() == updated
    assert updated.state == "failed" and updated.revision == 2
    assert timeline_failure_count() == 2 and warning.call_count == 1


def test_warning_sink_reentrant_timeline_failure_does_not_recurse_or_deadlock(
    tmp_path, monkeypatch
):
    path = tmp_path / "events.ndjson"
    fail_append(monkeypatch, path)
    nested = []

    def warning(*args, **kwargs):
        nested.append(event(path, event="nested"))

    sink = Mock(side_effect=warning)
    monkeypatch.setattr(timeline.logger, "warning", sink)
    outer = event(path, event="outer")
    assert outer["event"] == "outer" and nested[0]["event"] == "nested"
    assert timeline_failure_count() == 2 and sink.call_count == 1
