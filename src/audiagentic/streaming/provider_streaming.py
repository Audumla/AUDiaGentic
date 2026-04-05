"""Shared streaming command execution helpers for provider adapters."""
from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from audiagentic.streaming.sinks import ConsoleSink, InMemorySink, NormalizedEventSink, RawLogSink, StreamSink

@dataclass
class StreamedCommandResult:
    returncode: int
    stdout: str
    stderr: str
    command: list[str]


def _safe_sink_call(sink: StreamSink, method_name: str, *args: Any) -> None:
    method = getattr(sink, method_name)
    try:
        method(*args)
    except Exception:
        return None


def _reader(
    stream: TextIO,
    *,
    sinks: list[StreamSink],
) -> None:
    while True:
        line = stream.readline()
        if not line:
            break
        for sink in sinks:
            _safe_sink_call(sink, "write", line)
    for sink in sinks:
        _safe_sink_call(sink, "flush")
        _safe_sink_call(sink, "close")


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def build_provider_stream_sinks(
    *,
    packet_ctx: dict[str, Any],
    stream_controls: dict[str, Any] | None = None,
) -> tuple[list[StreamSink], list[StreamSink]]:
    runtime_root = None
    working_root = packet_ctx.get("working-root")
    job_id = packet_ctx.get("job-id")
    if working_root and job_id:
        runtime_root = Path(str(working_root)) / ".audiagentic" / "runtime" / "jobs" / str(job_id)

    stream_controls = stream_controls or {}
    enabled = bool(stream_controls.get("enabled", False))
    tee_console = bool(stream_controls.get("tee-console", False)) or enabled

    stdout_sinks: list[StreamSink] = [InMemorySink()]
    stderr_sinks: list[StreamSink] = [InMemorySink()]
    if runtime_root is not None:
        stdout_sinks.append(RawLogSink(runtime_root / "stdout.log"))
        stderr_sinks.append(RawLogSink(runtime_root / "stderr.log"))
        stdout_sinks.append(
            NormalizedEventSink(
                path=runtime_root / "events.ndjson",
                job_id=_string_or_none(packet_ctx.get("job-id")),
                prompt_id=_string_or_none(packet_ctx.get("prompt-id")),
                provider_id=_string_or_none(packet_ctx.get("provider-id")),
                surface=_string_or_none(packet_ctx.get("surface")),
                stage=_string_or_none(packet_ctx.get("stage") or packet_ctx.get("workflow-profile")),
                stream="stdout",
            )
        )
        stderr_sinks.append(
            NormalizedEventSink(
                path=runtime_root / "events.ndjson",
                job_id=_string_or_none(packet_ctx.get("job-id")),
                prompt_id=_string_or_none(packet_ctx.get("prompt-id")),
                provider_id=_string_or_none(packet_ctx.get("provider-id")),
                surface=_string_or_none(packet_ctx.get("surface")),
                stage=_string_or_none(packet_ctx.get("stage") or packet_ctx.get("workflow-profile")),
                stream="stderr",
            )
        )
    if tee_console:
        stdout_sinks.append(ConsoleSink())
        stderr_sinks.append(ConsoleSink(console=sys.stderr))
    return stdout_sinks, stderr_sinks


def run_streaming_command(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    stdout_sinks: list[StreamSink],
    stderr_sinks: list[StreamSink],
) -> StreamedCommandResult:
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd is not None else None,
        stdin=subprocess.PIPE if input_text is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    stdout_memory = next((sink for sink in stdout_sinks if isinstance(sink, InMemorySink)), None)
    stderr_memory = next((sink for sink in stderr_sinks if isinstance(sink, InMemorySink)), None)

    stdout_thread = threading.Thread(
        target=_reader,
        args=(process.stdout,),
        kwargs={"sinks": stdout_sinks},
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_reader,
        args=(process.stderr,),
        kwargs={"sinks": stderr_sinks},
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    if input_text is not None and process.stdin is not None:
        process.stdin.write(input_text)
        process.stdin.flush()
        process.stdin.close()

    returncode = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    return StreamedCommandResult(
        returncode=returncode,
        stdout=stdout_memory.text if stdout_memory is not None else "",
        stderr=stderr_memory.text if stderr_memory is not None else "",
        command=command,
    )
