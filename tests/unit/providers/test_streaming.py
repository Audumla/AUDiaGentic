from __future__ import annotations

import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.streaming import provider_streaming as streaming
from audiagentic.streaming.sinks import ConsoleSink
from audiagentic.streaming.sinks import InMemorySink


def test_run_streaming_command_captures_stdout_and_stderr(monkeypatch, tmp_path: Path) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.StringIO("stdout-one\nstdout-two\n")
            self.stderr = io.StringIO("stderr-one\n")
            self.stdin = None

        def wait(self) -> int:
            return 0

    captured: dict[str, object] = {}

    def fake_popen(command, **kwargs):  # type: ignore[no-untyped-def]
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(streaming.subprocess, "Popen", fake_popen)

    stdout_sinks, stderr_sinks = streaming.build_provider_stream_sinks(
        packet_ctx={
            "job-id": "job-123",
            "prompt-id": "prm-123",
            "provider-id": "cline",
            "working-root": str(tmp_path),
            "surface": "cli",
            "stage": "review",
        },
        stream_controls={"enabled": False},
    )

    result = streaming.run_streaming_command(
        ["tool", "--flag"],
        cwd=tmp_path,
        stdout_sinks=stdout_sinks,
        stderr_sinks=stderr_sinks,
    )

    assert result.returncode == 0
    assert result.stdout == "stdout-one\nstdout-two\n"
    assert result.stderr == "stderr-one\n"
    assert captured["command"] == ["tool", "--flag"]
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert (tmp_path / ".audiagentic" / "runtime" / "jobs" / "job-123" / "stdout.log").read_text(encoding="utf-8") == "stdout-one\nstdout-two\n"
    events_path = tmp_path / ".audiagentic" / "runtime" / "jobs" / "job-123" / "events.ndjson"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    assert len(events) == 3
    assert all(event["provider-id"] == "cline" for event in events)
    assert [event["details"]["stream"] for event in events].count("stdout") == 2
    assert [event["details"]["stream"] for event in events].count("stderr") == 1


def test_run_streaming_command_isolates_sink_failures(monkeypatch, tmp_path: Path) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.StringIO("hello\n")
            self.stderr = io.StringIO("")
            self.stdin = None

        def wait(self) -> int:
            return 0

    class FailingSink:
        def write(self, line: str) -> None:
            raise RuntimeError("boom")

        def flush(self) -> None:
            return None

        def close(self) -> None:
            return None

    def fake_popen(command, **kwargs):  # type: ignore[no-untyped-def]
        return FakeProcess()

    monkeypatch.setattr(streaming.subprocess, "Popen", fake_popen)

    memory_sink = InMemorySink()
    result = streaming.run_streaming_command(
        ["tool"],
        cwd=tmp_path,
        stdout_sinks=[FailingSink(), memory_sink],
        stderr_sinks=[InMemorySink()],
    )

    assert result.returncode == 0
    assert result.stdout == "hello\n"
    assert memory_sink.text == "hello\n"


def test_console_sink_replaces_unencodable_output() -> None:
    class FakeConsole:
        encoding = "cp1252"

        def __init__(self) -> None:
            self.calls = 0
            self.writes: list[str] = []

        def write(self, text: str) -> None:
            self.calls += 1
            if self.calls == 1:
                raise UnicodeEncodeError("cp1252", text, 0, 1, "bad char")
            self.writes.append(text)

        def flush(self) -> None:
            return None

    console = FakeConsole()
    sink = ConsoleSink(console=console)
    sink.write("done check \u2713\n")

    assert console.writes
    assert "?" in console.writes[0]
