"""Shared streaming command execution helpers for provider adapters."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from audiagentic.streaming.sinks import (
    ConsoleSink,
    InMemorySink,
    NormalizedEventSink,
    RawLogSink,
    StreamSink,
)


_logger = logging.getLogger(__name__)


@dataclass
class StreamedCommandResult:
    returncode: int
    stdout: str
    stderr: str
    command: list[str]


def _safe_sink_call(sink: StreamSink, method_name: str, *args: Any) -> None:
    import logging

    logger = logging.getLogger(__name__)
    method = getattr(sink, method_name)
    try:
        method(*args)
    except Exception as exc:
        logger.debug("sink %r.%s failed: %s", sink, method_name, exc)
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


def validate_stream_controls(
    stream_controls: dict[str, Any], policy: str = "normalize"
) -> dict[str, Any]:
    """Validate and normalize stream controls.

    Args:
        stream_controls: The stream controls dict to validate.
        policy: One of "normalize", "warn", or "fail".

    Returns:
        Normalized stream controls dict.

    Raises:
        ValueError: If policy is "fail" and validation fails.
    """
    import copy

    defaults = {
        "enabled": True,
        "tee-console": True,
        "timeout-warning-seconds": None,
        "timeout-seconds": None,
        "sink-error-policy": "warn",
        "control-validation-policy": "normalize",
        "termination-policy": "warn-only",
    }

    result = copy.deepcopy(defaults)
    result.update({k: v for k, v in stream_controls.items() if v is not None})

    valid_policies = {"warn", "fail", "normalize"}
    if result.get("sink-error-policy") not in valid_policies:
        if policy == "fail":
            raise ValueError(
                f"invalid sink-error-policy: {result.get('sink-error-policy')}"
            )
        elif policy == "warn":
            _logger.warning(
                "invalid sink-error-policy, using default: %s",
                result.get("sink-error-policy"),
            )
            result["sink-error-policy"] = "warn"

    valid_termination = {"graceful-kill", "warn-only"}
    if result.get("termination-policy") not in valid_termination:
        if policy == "fail":
            raise ValueError(
                f"invalid termination-policy: {result.get('termination-policy')}"
            )
        elif policy == "warn":
            _logger.warning(
                "invalid termination-policy, using default: %s",
                result.get("termination-policy"),
            )
            result["termination-policy"] = "warn-only"

    return result


def build_provider_stream_sinks(
    *,
    packet_ctx: dict[str, Any],
    stream_controls: dict[str, Any] | None = None,
) -> tuple[list[StreamSink], list[StreamSink]]:
    runtime_root = None
    working_root = packet_ctx.get("working-root")
    job_id = packet_ctx.get("job-id")
    if working_root and job_id:
        runtime_root = (
            Path(str(working_root)) / ".audiagentic" / "runtime" / "jobs" / str(job_id)
        )

    stream_controls = stream_controls or {}
    validated = validate_stream_controls(
        stream_controls,
        policy=stream_controls.get("control-validation-policy", "normalize"),
    )
    enabled = bool(validated.get("enabled", False))
    tee_console = validated.get("tee-console", enabled)

    stdout_sinks: list[StreamSink] = [InMemorySink()]
    stderr_sinks: list[StreamSink] = [InMemorySink()]
    if runtime_root is not None:
        stdout_sinks.append(RawLogSink(runtime_root / "stdout.log"))
        stderr_sinks.append(RawLogSink(runtime_root / "stderr.log"))
        job_id_str = str(job_id)
        stdout_sinks.append(
            NormalizedEventSink(
                path=runtime_root / "events.ndjson",
                job_id=job_id_str,
                prompt_id=_string_or_none(packet_ctx.get("prompt-id")),
                provider_id=_string_or_none(packet_ctx.get("provider-id")),
                surface=_string_or_none(packet_ctx.get("surface")),
                stage=_string_or_none(
                    packet_ctx.get("stage") or packet_ctx.get("workflow-profile")
                ),
                stream="stdout",
            )
        )
        stderr_sinks.append(
            NormalizedEventSink(
                path=runtime_root / "events.ndjson",
                job_id=job_id_str,
                prompt_id=_string_or_none(packet_ctx.get("prompt-id")),
                provider_id=_string_or_none(packet_ctx.get("provider-id")),
                surface=_string_or_none(packet_ctx.get("surface")),
                stage=_string_or_none(
                    packet_ctx.get("stage") or packet_ctx.get("workflow-profile")
                ),
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
    timeout_warning_seconds: float | None = None,
    timeout_seconds: float | None = None,
    termination_policy: str = "warn-only",
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

    stdout_memory = next(
        (sink for sink in stdout_sinks if isinstance(sink, InMemorySink)), None
    )
    stderr_memory = next(
        (sink for sink in stderr_sinks if isinstance(sink, InMemorySink)), None
    )

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

    start_time = time.monotonic()
    timed_out = False
    warning_emitted = False

    try:
        while True:
            returncode = process.poll()
            if returncode is not None:
                break

            elapsed = time.monotonic() - start_time

            if timeout_warning_seconds and not warning_emitted:
                if elapsed >= timeout_warning_seconds:
                    _logger.warning(
                        "stream timeout warning: %.1fs exceeded for command %s",
                        timeout_warning_seconds,
                        command[0] if command else "unknown",
                    )
                    warning_emitted = True

            if timeout_seconds and elapsed >= timeout_seconds:
                timed_out = True
                if termination_policy == "graceful-kill":
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                elif termination_policy == "warn-only":
                    _logger.warning(
                        "stream timeout reached (%.1fs) but termination-policy is warn-only; process will continue",
                        timeout_seconds,
                    )
                break

            time.sleep(0.1)
    finally:
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)

    if timed_out and termination_policy == "graceful-kill":
        returncode = -1

    return StreamedCommandResult(
        returncode=returncode,
        stdout=stdout_memory.text if stdout_memory is not None else "",
        stderr=stderr_memory.text if stderr_memory is not None else "",
        command=command,
    )
