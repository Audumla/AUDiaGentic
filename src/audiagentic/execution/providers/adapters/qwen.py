"""Qwen provider adapter."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.streaming.completion import (
    NormalizationMethod,
    ResultSource,
    build_synthetic_fallback,
    normalize_provider_result,
    persist_completion,
    try_extract_json_from_stdout,
)
from audiagentic.streaming.provider_streaming import (
    build_provider_stream_sinks,
    run_streaming_command,
)
from audiagentic.streaming.sinks import NormalizedEventSink, StreamSink


class QwenEventExtractor:
    """Extract Qwen events from stream output.

    This sink parses Qwen plain-text output and translates it into canonical
    provider-stream-event records before forwarding to NormalizedEventSink.
    """

    def __init__(
        self,
        event_sink: NormalizedEventSink,
        job_id: str | None = None,
        provider_id: str = "qwen",
    ) -> None:
        self.event_sink = event_sink
        self.job_id = job_id
        self.provider_id = provider_id

    def write(self, line: str) -> None:
        """Process a line and extract Qwen events."""
        text = line.rstrip("\r\n")
        if not text:
            return

        # Try to parse as JSON for structured events
        try:
            message = json.loads(text)
            if isinstance(message, dict):
                # For future JSON-format support, map event types here
                # For now, all JSON events and text are task-progress
                self._emit_event("task-progress", text, message)
            else:
                self._emit_event("task-progress", text)
        except json.JSONDecodeError:
            # Plain text line
            self._emit_event("task-progress", text)

    def _emit_event(
        self,
        event_kind: str,
        message: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a canonical event through the underlying sink."""
        details: dict[str, Any] = {"extractor": "qwen-plaintext"}
        if raw_payload:
            details["raw"] = raw_payload

        self.event_sink.write_event(
            {
                "contract-version": "v1",
                "job-id": self.job_id,
                "provider-id": self.provider_id,
                "event-kind": event_kind,
                "message": message,
                "timestamp": _utc_now(),
                "details": details,
            }
        )

    def flush(self) -> None:
        self.event_sink.flush()

    def close(self) -> None:
        self.event_sink.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_qwen_stream_sinks(
    *,
    packet_ctx: dict[str, Any],
    stream_controls: dict[str, Any] | None = None,
) -> tuple[list[StreamSink], list[StreamSink]]:
    """Build Qwen-specific stream sinks with event extraction.

    This adds QwenEventExtractor on top of the standard sinks to parse
    Qwen output into canonical events.
    """
    # Build base sinks
    stdout_sinks, stderr_sinks = build_provider_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    # Find the NormalizedEventSink for stdout and wrap it with QwenEventExtractor
    job_id = packet_ctx.get("job-id")
    for i, sink in enumerate(stdout_sinks):
        if isinstance(sink, NormalizedEventSink):
            # Replace with QwenEventExtractor that wraps the original sink
            stdout_sinks[i] = QwenEventExtractor(
                event_sink=sink,
                job_id=job_id,
                provider_id="qwen",
            )
            break

    return stdout_sinks, stderr_sinks


def _build_prompt(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> str:
    prompt_body = packet_ctx.get("prompt-body")
    prompt = (
        "AUDiaGentic Qwen provider execution request. "
        f"job={packet_ctx.get('job-id')} "
        f"packet={packet_ctx.get('packet-id')} "
        f"provider={packet_ctx.get('provider-id', 'qwen')} "
        f"model={provider_cfg.get('default-model')} "
        f"workflow={packet_ctx.get('workflow-profile')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible."
    )
    if prompt_body:
        prompt += f" Prompt body: {str(prompt_body).strip()}"
    return prompt.strip()


def _qwen_executable() -> str:
    executable = shutil.which("qwen")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-007",
            kind="external",
            message="qwen command is not available on PATH",
            details={"provider-id": "qwen"},
        )
    return executable


def _parse_qwen_completion(
    stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
    """Parse Qwen completion from stdout.

    Returns:
        tuple[dict[str, Any] | None, ResultSource]: (parsed_data, source)
    """
    # Try to parse full stdout as JSON
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            return data, ResultSource.STDOUT_JSON
    except (json.JSONDecodeError, ValueError):
        pass

    extracted = try_extract_json_from_stdout(stdout)
    if extracted:
        return extracted, ResultSource.STDOUT_JSON_BLOCK

    return None, ResultSource.STDOUT_TEXT


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _qwen_executable()
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = provider_cfg.get("default-model")
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    execution_policy = provider_cfg.get("execution-policy", {})
    approval_mode = execution_policy.get("permission-mode", "auto")

    # Qwen CLI uses positional arguments for prompt
    command = [executable]
    if approval_mode == "yolo":
        command.append("--yolo")
    elif approval_mode == "auto-edit":
        command.extend(["--approval-mode", "auto-edit"])
    if default_model:
        command.extend(["-m", str(default_model)])
    # Add prompt as positional argument
    command.append(prompt)

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_qwen_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    completed = run_streaming_command(
        command,
        cwd=cwd,
        stdout_sinks=stdout_sinks,
        stderr_sinks=stderr_sinks,
    )
    stdout_text = completed.stdout.strip()
    stderr_text = completed.stderr.strip()

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-008",
            kind="external",
            message="qwen execution failed",
            details={
                "provider-id": "qwen",
                "returncode": completed.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "command": command,
            },
        )

    # Parse structured completion
    parsed_data, result_source = _parse_qwen_completion(
        stdout_text, stderr_text, completed.returncode
    )

    # Build canonical completion
    if parsed_data and result_source != ResultSource.STDOUT_TEXT:
        completion = normalize_provider_result(
            provider_id="qwen",
            job_id=packet_ctx.get("job-id"),
            prompt_id=packet_ctx.get("prompt-id"),
            surface=packet_ctx.get("surface"),
            stage=packet_ctx.get("workflow-profile"),
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=completed.returncode,
            result_source=result_source,
            normalization_method=NormalizationMethod.PROVIDER_NATIVE_JSON,
            subject=parsed_data,
        )
    else:
        completion = build_synthetic_fallback(
            provider_id="qwen",
            job_id=packet_ctx.get("job-id"),
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=completed.returncode,
        )

    # Persist completion
    working_root_path = Path(working_root) if working_root else None
    if working_root_path and packet_ctx.get("job-id"):
        try:
            persist_completion(working_root_path, packet_ctx.get("job-id"), completion)
        except AudiaGenticError:
            pass

    return {
        "provider-id": packet_ctx.get("provider-id", "qwen"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "output": stdout_text,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "returncode": completed.returncode,
        "command": command,
        "completion": completion.to_dict(),
    }
