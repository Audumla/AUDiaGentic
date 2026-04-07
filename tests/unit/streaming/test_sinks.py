"""Tests for stream sink edge cases and validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.streaming.sinks import (
    ConsoleSink,
    InMemorySink,
    NormalizedEventSink,
    RawLogSink,
    StreamSink,
)


class TestNormalizedEventSinkValidation:
    """Test schema validation in NormalizedEventSink."""

    def test_valid_event_writes_successfully(self, tmp_path: Path) -> None:
        """Valid events should be written without issues."""
        event_path = tmp_path / "events.ndjson"
        sink = NormalizedEventSink(
            path=event_path,
            job_id="job-123",
            provider_id="test",
        )

        sink.write_event(
            {
                "contract-version": "v1",
                "job-id": "job-123",
                "provider-id": "test",
                "event-kind": "task-progress",
                "message": "test message",
                "timestamp": "2024-01-01T00:00:00Z",
            }
        )

        content = event_path.read_text(encoding="utf-8")
        record = json.loads(content.strip())
        assert record["job-id"] == "job-123"
        assert record["event-kind"] == "task-progress"

    def test_missing_required_field_skips_write(self, tmp_path: Path) -> None:
        """Events missing required fields should not be written."""
        event_path = tmp_path / "events.ndjson"
        sink = NormalizedEventSink(
            path=event_path,
            job_id="job-123",
            provider_id="test",
        )

        sink.write_event(
            {
                "contract-version": "v1",
                "job-id": "job-123",
                "provider-id": "test",
                "event-kind": "task-progress",
            }
        )

        assert not event_path.exists()

    def test_missing_message_field_skips_write(self, tmp_path: Path) -> None:
        """Events missing message field should not be written."""
        event_path = tmp_path / "events.ndjson"
        sink = NormalizedEventSink(
            path=event_path,
            job_id="job-123",
            provider_id="test",
        )

        sink.write_event(
            {
                "contract-version": "v1",
                "job-id": "job-123",
                "provider-id": "test",
                "event-kind": "task-progress",
                "timestamp": "2024-01-01T00:00:00Z",
            }
        )

        assert not event_path.exists()

    def test_null_values_filtered_from_record(self, tmp_path: Path) -> None:
        """Null values should be filtered from the written record."""
        event_path = tmp_path / "events.ndjson"
        sink = NormalizedEventSink(
            path=event_path,
            job_id="job-123",
            provider_id="test",
            prompt_id=None,
            surface=None,
        )

        sink.write_event(
            {
                "contract-version": "v1",
                "job-id": "job-123",
                "provider-id": "test",
                "prompt-id": None,
                "surface": None,
                "event-kind": "task-progress",
                "message": "test",
                "timestamp": "2024-01-01T00:00:00Z",
            }
        )

        content = event_path.read_text(encoding="utf-8")
        record = json.loads(content.strip())
        assert "prompt-id" not in record
        assert "surface" not in record


class TestNormalizedEventSinkJobIdRequirement:
    """Test that job_id is required for NormalizedEventSink."""

    def test_job_id_type_hint_is_str(self, tmp_path: Path) -> None:
        """job_id type hint should be str (not str | None)."""
        import inspect

        sig = inspect.signature(NormalizedEventSink.__init__)
        job_id_param = sig.parameters.get("job_id")
        assert job_id_param is not None
        annotation = str(job_id_param.annotation)
        assert annotation == "str"

    def test_job_id_is_string(self, tmp_path: Path) -> None:
        """job_id should be a string."""
        sink = NormalizedEventSink(
            path=tmp_path / "events.ndjson",
            job_id="job-123",
            provider_id="test",
        )
        assert sink.job_id == "job-123"


class TestRawLogSinkDirectoryCreation:
    """Test that RawLogSink creates directories at construction."""

    def test_directory_created_at_construction(self, tmp_path: Path) -> None:
        """Directory should be created when sink is constructed."""
        log_path = tmp_path / "nested" / "dir" / "log.txt"
        assert not log_path.parent.exists()

        sink = RawLogSink(path=log_path)

        assert log_path.parent.exists()

    def test_no_directory_creation_on_write(self, tmp_path: Path) -> None:
        """Directory creation should not happen on every write."""
        log_path = tmp_path / "log.txt"
        sink = RawLogSink(path=log_path)

        sink.write("line 1")
        sink.write("line 2")

        content = log_path.read_text(encoding="utf-8")
        assert "line 1" in content
        assert "line 2" in content


class TestInMemorySink:
    """Test InMemorySink behavior."""

    def test_collects_lines(self) -> None:
        """InMemorySink should collect all lines."""
        sink = InMemorySink()
        sink.write("line 1\n")
        sink.write("line 2\n")

        assert sink.text == "line 1\nline 2\n"

    def test_empty_lines_included(self) -> None:
        """Empty lines should be included."""
        sink = InMemorySink()
        sink.write("\n")

        assert sink.text == "\n"


class TestConsoleSink:
    """Test ConsoleSink behavior."""

    def test_writes_to_provided_console(self) -> None:
        """ConsoleSink should write to the provided console."""
        from io import StringIO

        output = StringIO()
        sink = ConsoleSink(console=output)
        sink.write("test output")

        assert "test output" in output.getvalue()

    def test_handles_unicode_encode_error(self) -> None:
        """ConsoleSink should handle unicode encode errors gracefully."""
        from io import StringIO

        output = StringIO()
        sink = ConsoleSink(console=output)
        sink.write("test \xff output")

        result = output.getvalue()
        assert "test" in result


class TestSafeSinkCall:
    """Test _safe_sink_call error isolation."""

    def test_successful_call(self) -> None:
        """Successful calls should complete without issues."""
        from audiagentic.streaming.provider_streaming import _safe_sink_call

        sink = InMemorySink()
        _safe_sink_call(sink, "write", "test")
        assert sink.text == "test"

    def test_failed_call_does_not_propagate(self) -> None:
        """Failed calls should not propagate exceptions."""
        from audiagentic.streaming.provider_streaming import _safe_sink_call

        class FailingSink:
            def write(self, _):
                raise ValueError("intentional failure")

            def flush(self):
                pass

            def close(self):
                pass

        sink = FailingSink()
        _safe_sink_call(sink, "write", "test")

    def test_failed_call_logs_debug(self, caplog) -> None:
        """Failed calls should log at debug level."""
        from audiagentic.streaming.provider_streaming import _safe_sink_call

        class FailingSink:
            def write(self, _):
                raise ValueError("intentional failure")

            def flush(self):
                pass

            def close(self):
                pass

        sink = FailingSink()
        with caplog.at_level("DEBUG"):
            _safe_sink_call(sink, "write", "test")

        assert any("intentional failure" in record.message for record in caplog.records)


class TestBuildProviderStreamSinks:
    """Test build_provider_stream_sinks edge cases."""

    def test_no_runtime_root_without_job_id(self, tmp_path: Path) -> None:
        """No runtime sinks should be created without job-id."""
        from audiagentic.streaming.provider_streaming import (
            build_provider_stream_sinks,
        )

        stdout_sinks, stderr_sinks = build_provider_stream_sinks(
            packet_ctx={
                "working-root": str(tmp_path),
                "job-id": None,
            },
            stream_controls={},
        )

        assert len(stdout_sinks) == 2
        assert isinstance(stdout_sinks[0], InMemorySink)
        assert isinstance(stdout_sinks[1], ConsoleSink)
        assert len(stderr_sinks) == 2
        assert isinstance(stderr_sinks[0], InMemorySink)
        assert isinstance(stderr_sinks[1], ConsoleSink)

    def test_no_runtime_root_without_working_root(self, tmp_path: Path) -> None:
        """No runtime sinks should be created without working-root."""
        from audiagentic.streaming.provider_streaming import (
            build_provider_stream_sinks,
        )

        stdout_sinks, stderr_sinks = build_provider_stream_sinks(
            packet_ctx={
                "working-root": None,
                "job-id": "job-123",
            },
            stream_controls={},
        )

        assert len(stdout_sinks) == 2
        assert isinstance(stdout_sinks[0], InMemorySink)
        assert isinstance(stdout_sinks[1], ConsoleSink)

    def test_runtime_sinks_created_with_both(self, tmp_path: Path) -> None:
        """Runtime sinks should be created when both are provided."""
        from audiagentic.streaming.provider_streaming import (
            build_provider_stream_sinks,
        )

        stdout_sinks, stderr_sinks = build_provider_stream_sinks(
            packet_ctx={
                "working-root": str(tmp_path),
                "job-id": "job-123",
                "provider-id": "test",
                "surface": "cli",
                "workflow-profile": "standard",
            },
            stream_controls={},
        )

        assert len(stdout_sinks) == 4
        assert isinstance(stdout_sinks[0], InMemorySink)
        assert isinstance(stdout_sinks[1], RawLogSink)
        assert isinstance(stdout_sinks[2], NormalizedEventSink)
        assert isinstance(stdout_sinks[3], ConsoleSink)

    def test_normalized_event_sink_has_job_id(self, tmp_path: Path) -> None:
        """NormalizedEventSink should always have a job_id."""
        from audiagentic.streaming.provider_streaming import (
            build_provider_stream_sinks,
        )

        stdout_sinks, _ = build_provider_stream_sinks(
            packet_ctx={
                "working-root": str(tmp_path),
                "job-id": "job-123",
                "provider-id": "test",
            },
            stream_controls={},
        )

        event_sink = next(s for s in stdout_sinks if isinstance(s, NormalizedEventSink))
        assert event_sink.job_id == "job-123"


class TestStreamControlsValidation:
    """Test stream controls handling."""

    def test_empty_stream_controls(self, tmp_path: Path) -> None:
        """Empty stream controls should work."""
        from audiagentic.streaming.provider_streaming import (
            build_provider_stream_sinks,
        )

        stdout_sinks, stderr_sinks = build_provider_stream_sinks(
            packet_ctx={
                "working-root": str(tmp_path),
                "job-id": "job-123",
            },
            stream_controls={},
        )

        assert len(stdout_sinks) == 4

    def test_none_stream_controls(self, tmp_path: Path) -> None:
        """None stream controls should work."""
        from audiagentic.streaming.provider_streaming import (
            build_provider_stream_sinks,
        )

        stdout_sinks, stderr_sinks = build_provider_stream_sinks(
            packet_ctx={
                "working-root": str(tmp_path),
                "job-id": "job-123",
            },
            stream_controls=None,
        )

        assert len(stdout_sinks) == 4

    def test_tee_console_enabled(self, tmp_path: Path) -> None:
        """tee-console should add ConsoleSink (already enabled by default)."""
        from audiagentic.streaming.provider_streaming import (
            build_provider_stream_sinks,
        )

        stdout_sinks, stderr_sinks = build_provider_stream_sinks(
            packet_ctx={
                "working-root": str(tmp_path),
                "job-id": "job-123",
            },
            stream_controls={"tee-console": True},
        )

        assert len(stdout_sinks) == 4
        assert isinstance(stdout_sinks[3], ConsoleSink)

    def test_tee_console_disabled(self, tmp_path: Path) -> None:
        """tee-console=False should not add ConsoleSink."""
        from audiagentic.streaming.provider_streaming import (
            build_provider_stream_sinks,
        )

        stdout_sinks, stderr_sinks = build_provider_stream_sinks(
            packet_ctx={
                "working-root": str(tmp_path),
                "job-id": "job-123",
            },
            stream_controls={"tee-console": False},
        )

        assert len(stdout_sinks) == 3
        assert not any(isinstance(s, ConsoleSink) for s in stdout_sinks)

    def test_enabled_implies_tee_console(self, tmp_path: Path) -> None:
        """enabled=True should imply tee-console (already enabled by default)."""
        from audiagentic.streaming.provider_streaming import (
            build_provider_stream_sinks,
        )

        stdout_sinks, stderr_sinks = build_provider_stream_sinks(
            packet_ctx={
                "working-root": str(tmp_path),
                "job-id": "job-123",
            },
            stream_controls={"enabled": True},
        )

        assert len(stdout_sinks) == 4
        assert isinstance(stdout_sinks[3], ConsoleSink)
