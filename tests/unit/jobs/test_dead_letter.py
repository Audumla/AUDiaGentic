"""Tests for dead_letter module (EDJ12)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from audiagentic.components.agent_jobs.dead_letter import (
    dead_letter_path,
    read_dead_letters,
    write_dead_letter,
)
from audiagentic.foundation.contracts.error_resolutions import (
    load_all_error_resolutions,
)
from audiagentic.foundation.contracts.errors import (
    AudiaGenticError,
    get_error_resolution,
)


@pytest.fixture(autouse=True, scope="session")
def _load_error_resolutions() -> None:
    config_dirs = [
        Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"
    ]
    load_all_error_resolutions(config_dirs)


def _minimal_record(overrides: dict | None = None) -> dict:
    base = {
        "event_type": "agent_jobs.job.completed",
        "payload_summary": "job-completion event for job_001",
        "metadata": {"subject": "test-subject"},
        "trigger_id": "trg-001",
        "job_id": "job_001",
        "error_code": "EXT-PV-001",
        "error_message": "provider timeout",
        "correlation_id": "corr-abc-123",
    }
    if overrides:
        base.update(overrides)
    return base


class TestWriteDeadLetter:
    def test_failing_handler_writes_one_redacted_entry(self, tmp_path: Path) -> None:
        record = _minimal_record()
        write_dead_letter(tmp_path, record)

        entries = read_dead_letters(tmp_path)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["event_type"] == "agent_jobs.job.completed"
        assert entry["trigger_id"] == "trg-001"
        assert entry["job_id"] == "job_001"
        assert entry["correlation_id"] == "corr-abc-123"
        assert entry["error_code"] == "EXT-PV-001"
        assert "timestamp" in entry

    def test_entry_round_trips_with_re_fire_inputs(self, tmp_path: Path) -> None:
        record = _minimal_record(
            {
                "metadata": {
                    "subject": "job-result",
                    "re_fire_event_type": "agent_jobs.job.completed",
                    "re_fire_trigger_id": "trg-001",
                }
            }
        )
        write_dead_letter(tmp_path, record)

        entries = read_dead_letters(tmp_path)
        assert len(entries) == 1
        entry = entries[0]
        # Verify re-fire inputs survive round-trip
        assert entry["metadata"]["re_fire_event_type"] == "agent_jobs.job.completed"
        assert entry["metadata"]["re_fire_trigger_id"] == "trg-001"
        # All keys must be parseable strings (no nested non-json-safe objects)
        for value in entry.values():
            json.dumps(value)  # would raise if non-serializable

    def test_no_raw_payload_or_prompt_in_entry(self, tmp_path: Path) -> None:
        record = _minimal_record()
        # Attempting to include denylisted fields must be rejected by
        # append_operational_record (CON-OPR-002).
        record["prompt-body"] = "this should never appear"
        with pytest.raises(AudiaGenticError) as exc_info:
            write_dead_letter(tmp_path, record)
        assert exc_info.value.code == "CON-OPR-002"

        # Also verify the file is empty (no partial write).
        entries = read_dead_letters(tmp_path)
        assert len(entries) == 0

    def test_no_raw_output_in_entry(self, tmp_path: Path) -> None:
        record = _minimal_record()
        record["output"] = "model response text"
        with pytest.raises(AudiaGenticError) as exc_info:
            write_dead_letter(tmp_path, record)
        assert exc_info.value.code == "CON-OPR-002"

    def test_payload_summary_truncated_at_500_chars(self, tmp_path: Path) -> None:
        long_summary = "x" * 600
        record = _minimal_record({"payload_summary": long_summary})
        write_dead_letter(tmp_path, record)

        entries = read_dead_letters(tmp_path)
        assert len(entries) == 1
        summary = entries[0]["payload_summary"]
        assert len(summary) <= 500
        assert summary.endswith("...")

    def test_timestamp_injected_when_absent(self, tmp_path: Path) -> None:
        record = _minimal_record()
        # _minimal_record does not include timestamp; it will be injected by write_dead_letter
        assert "timestamp" not in record
        write_dead_letter(tmp_path, record)

        entries = read_dead_letters(tmp_path)
        assert len(entries) == 1
        assert "timestamp" in entries[0]
        ts = entries[0]["timestamp"]
        assert isinstance(ts, str)
        assert len(ts) > 10  # basic sanity: looks like an ISO string

    def test_correlation_id_filled_when_absent(self, tmp_path: Path) -> None:
        record = _minimal_record()
        del record["correlation_id"]
        write_dead_letter(tmp_path, record)

        entries = read_dead_letters(tmp_path)
        assert len(entries) == 1
        assert "correlation_id" in entries[0]

    def test_multiple_entries_append(self, tmp_path: Path) -> None:
        for i in range(3):
            write_dead_letter(
                tmp_path,
                _minimal_record(
                    {
                        "trigger_id": f"trg-{i}",
                        "job_id": f"job_{i:03d}",
                        "correlation_id": f"corr-{i}",
                    }
                ),
            )

        entries = read_dead_letters(tmp_path)
        assert len(entries) == 3
        ids = [e["trigger_id"] for e in entries]
        assert ids == ["trg-0", "trg-1", "trg-2"]


class TestMissingRequiredFields:
    def test_missing_event_type_raises_VAL_DL_002(self, tmp_path: Path) -> None:
        record = _minimal_record()
        del record["event_type"]
        with pytest.raises(AudiaGenticError) as exc_info:
            write_dead_letter(tmp_path, record)
        assert exc_info.value.code == "VAL-DL-002"

    def test_missing_payload_summary_raises_VAL_DL_002(self, tmp_path: Path) -> None:
        record = _minimal_record()
        del record["payload_summary"]
        with pytest.raises(AudiaGenticError) as exc_info:
            write_dead_letter(tmp_path, record)
        assert exc_info.value.code == "VAL-DL-002"

    def test_missing_error_code_raises_VAL_DL_002(self, tmp_path: Path) -> None:
        record = _minimal_record()
        del record["error_code"]
        with pytest.raises(AudiaGenticError) as exc_info:
            write_dead_letter(tmp_path, record)
        assert exc_info.value.code == "VAL-DL-002"


class TestWriteFailure:
    def test_io_failure_raises_IO_DL_001(self, tmp_path: Path) -> None:
        """When append_operational_record raises an unexpected IOError,
        write_dead_letter wraps it as IO-DL-001."""
        record = _minimal_record()

        def raise_ioerror(*a, **k):  # noqa: ARG001
            raise OSError("disk full")

        with patch(
            "audiagentic.components.agent_jobs.dead_letter.append_operational_record",
            side_effect=raise_ioerror,
        ):
            with pytest.raises(AudiaGenticError) as exc_info:
                write_dead_letter(tmp_path, record)
            assert exc_info.value.code == "IO-DL-001"


class TestReadDeadLetters:
    def test_returns_empty_when_file_missing(self, tmp_path: Path) -> None:
        assert read_dead_letters(tmp_path) == []

    def test_returns_empty_for_empty_file(self, tmp_path: Path) -> None:
        dl_path = dead_letter_path(tmp_path)
        dl_path.parent.mkdir(parents=True, exist_ok=True)
        dl_path.write_text("", encoding="utf-8")
        assert read_dead_letters(tmp_path) == []

    def test_skips_malformed_json_lines(self, tmp_path: Path) -> None:
        dl_path = dead_letter_path(tmp_path)
        dl_path.parent.mkdir(parents=True, exist_ok=True)
        good = json.dumps({"correlation_id": "x", "data": 1})
        dl_path.write_text(f"{good}\nnot-json\n{good}\n", encoding="utf-8")

        entries = read_dead_letters(tmp_path)
        assert len(entries) == 2


class TestErrorResolutionsRegistered:
    def test_dl_error_codes_have_resolutions(self) -> None:
        for code in ("IO-DL-001", "VAL-DL-002"):
            resolution = get_error_resolution(code)
            assert resolution is not None, f"Missing error resolution for {code}"
            assert isinstance(resolution, str)
            assert len(resolution) > 0
