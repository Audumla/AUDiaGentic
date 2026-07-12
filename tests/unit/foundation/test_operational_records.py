"""Unit tests for append_operational_record (EDJ20)."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_ndjson
from audiagentic.foundation.observability.operational_records import append_operational_record


class TestAppendOperationalRecordBasics:
    def test_appends_valid_json_line(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        record = {"correlation_id": "abc-123", "event": "test-started"}
        append_operational_record(path, record)

        entries = load_ndjson(path)
        assert len(entries) == 1
        assert entries[0]["correlation_id"] == "abc-123"
        assert entries[0]["event"] == "test-started"
        assert "timestamp" in entries[0]

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "dir" / "records.ndjson"
        record = {"correlation_id": "x", "data": 1}
        append_operational_record(path, record)

        assert path.exists()
        entries = load_ndjson(path)
        assert len(entries) == 1

    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        for i in range(5):
            append_operational_record(path, {"correlation_id": f"id-{i}", "idx": i})

        entries = load_ndjson(path)
        assert len(entries) == 5
        for idx, entry in enumerate(entries):
            assert entry["idx"] == idx


class TestTimestampInjection:
    def test_injects_timestamp_when_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        record = {"correlation_id": "ts-test", "value": 1}
        append_operational_record(path, record)

        entries = load_ndjson(path)
        assert "timestamp" in entries[0]
        assert entries[0]["timestamp"].endswith("Z") or "+" in entries[0]["timestamp"]

    def test_preserves_existing_timestamp(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        fixed_ts = "2025-01-01T00:00:00Z"
        record = {"correlation_id": "ts-test", "timestamp": fixed_ts, "value": 1}
        append_operational_record(path, record)

        entries = load_ndjson(path)
        assert entries[0]["timestamp"] == fixed_ts


class TestCorrelationIdValidation:
    def test_rejects_missing_correlation_id(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        record = {"event": "no-corr"}
        with pytest.raises(AudiaGenticError, match="VAL-OPR-001"):
            append_operational_record(path, record)

    def test_accepts_null_correlation_id(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        record = {"correlation_id": None, "event": "nullable-corr"}
        append_operational_record(path, record)

        entries = load_ndjson(path)
        assert entries[0]["correlation_id"] is None

    def test_accepts_empty_string_correlation_id(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        record = {"correlation_id": "", "event": "empty-corr"}
        append_operational_record(path, record)

        entries = load_ndjson(path)
        assert entries[0]["correlation_id"] == ""


class TestRedactionDenylist:
    denylist_keys = ["prompt-body", "output", "prompt_body", "raw_output"]

    @pytest.mark.parametrize("denied_key", denylist_keys)
    def test_rejects_denylisted_fields(self, tmp_path: Path, denied_key: str) -> None:
        path = tmp_path / "records.ndjson"
        record = {"correlation_id": "redact-test", denied_key: "sensitive"}
        with pytest.raises(AudiaGenticError, match="CON-OPR-002"):
            append_operational_record(path, record)

    def test_accepts_safe_fields(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        record = {
            "correlation_id": "safe",
            "event-type": "normal",
            "result_summary": "ok",
        }
        append_operational_record(path, record)
        entries = load_ndjson(path)
        assert len(entries) == 1

    @pytest.mark.parametrize("denied_key", denylist_keys)
    def test_rejects_nested_denylisted_fields(self, tmp_path: Path, denied_key: str) -> None:
        """EDJ24: the denylist is recursive — nested mappings are inspected too."""
        path = tmp_path / "records.ndjson"
        record = {
            "correlation_id": "nested-redact",
            "metadata": {"inner": {denied_key: "sensitive"}},
        }
        with pytest.raises(AudiaGenticError, match="CON-OPR-002"):
            append_operational_record(path, record)
        assert not path.exists(), "no partial write on rejection"

    def test_rejects_denylisted_key_inside_list(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        record = {
            "correlation_id": "list-redact",
            "entries": [{"ok": 1}, {"api_key": "sk-123"}],
        }
        with pytest.raises(AudiaGenticError, match="CON-OPR-002"):
            append_operational_record(path, record)

    def test_benign_nested_values_persist(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        record = {
            "correlation_id": "benign-nested",
            "metadata": {"subject": {"kind": "job", "id": "job-1"}, "trigger-id": "t-1"},
            "entries": [{"status": "fired"}],
        }
        append_operational_record(path, record)
        entries = load_ndjson(path)
        assert entries[0]["metadata"]["subject"]["id"] == "job-1"

    def test_string_contents_not_inspected(self, tmp_path: Path) -> None:
        """Values are the caller's responsibility (summarize/redact before write)."""
        path = tmp_path / "records.ndjson"
        record = {
            "correlation_id": "strings-ok",
            "summary": "mentions the word prompt-body inside a string",
        }
        append_operational_record(path, record)
        assert len(load_ndjson(path)) == 1


class TestNdjsonRoundTrip:
    def test_each_line_is_valid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "records.ndjson"
        for i in range(20):
            append_operational_record(path, {"correlation_id": f"rt-{i}", "data": {"nested": i}})

        raw = path.read_text(encoding="utf-8")
        lines = [line for line in raw.splitlines() if line.strip()]
        assert len(lines) == 20
        for line in lines:
            obj = json.loads(line)
            assert isinstance(obj, dict)


class TestConcurrentAppends:
    def test_concurrent_threads_no_corruption(self, tmp_path: Path) -> None:
        path = tmp_path / "concurrent.ndjson"
        num_threads = 16
        records_per_thread = 50
        barrier = threading.Barrier(num_threads)

        def worker(thread_id: int) -> None:
            barrier.wait(timeout=5)
            for i in range(records_per_thread):
                append_operational_record(
                    path,
                    {
                        "correlation_id": f"thread-{thread_id}",
                        "thread": thread_id,
                        "seq": i,
                    },
                )

        with ThreadPoolExecutor(max_workers=num_threads) as pool:
            futures = [pool.submit(worker, tid) for tid in range(num_threads)]
            for f in futures:
                f.result(timeout=30)

        entries = load_ndjson(path)
        assert len(entries) == num_threads * records_per_thread

    def test_concurrent_lines_are_not_interleaved(self, tmp_path: Path) -> None:
        path = tmp_path / "no-interleave.ndjson"
        record_size = 1024

        def write_big(tid: int) -> None:
            for i in range(10):
                append_operational_record(
                    path,
                    {
                        "correlation_id": f"big-{tid}",
                        "payload": "A" * record_size,
                        "idx": i,
                    },
                )

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(write_big, tid) for tid in range(8)]
            for f in futures:
                f.result(timeout=30)

        raw_lines = path.read_text(encoding="utf-8").splitlines()
        valid_count = 0
        for line in raw_lines:
            if not line.strip():
                continue
            obj = json.loads(line)
            assert isinstance(obj, dict), f"Line is not a JSON object: {line[:100]}"
            valid_count += 1

        assert valid_count == 80


class TestAppendOperationalRecordDurability:
    def test_fsync_is_called_after_write(self, tmp_path: Path) -> None:
        import os
        from unittest.mock import patch

        path = tmp_path / "fsync-test.ndjson"
        with patch.object(os, "fsync") as mock_fsync:
            append_operational_record(path, {"correlation_id": "fsync-01", "data": 1})
            mock_fsync.assert_called_once()
