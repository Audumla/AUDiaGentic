"""opencode provider adapter."""

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


class OpencodeEventExtractor:
    """Extract opencode events from stream output.

    This sink parses opencode NDJSON events and translates them into canonical
    provider-stream-event records before forwarding to NormalizedEventSink.
    """

    # opencode event type to canonical event kind mapping
    EVENT_KIND_MAP = {
        "session.started": "task-start",
        "assistant.message": "task-progress",
        "tool.call": "tool-call",
        "tool.result": "tool-result",
        "error": "error",
        "session.complete": "completion",
    }

    def __init__(
        self,
        event_sink: NormalizedEventSink,
        job_id: str | None = None,
        provider_id: str = "opencode",
    ) -> None:
        self.event_sink = event_sink
        self.job_id = job_id
        self.provider_id = provider_id

    def write(self, line: str) -> None:
        """Process a line and extract opencode NDJSON events."""
        text = line.rstrip("\r\n")
        if not text:
            return

        # Try to parse as NDJSON
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            # Pass through non-JSON lines as task-progress
            self._emit_event("task-progress", text)
            return

        if not isinstance(message, dict):
            self._emit_event("task-progress", text)
            return

        # Extract event type and map to canonical kind
        event_type = message.get("type")
        event_kind = self.EVENT_KIND_MAP.get(event_type, "task-progress")

        # Extract message content
        message_text = (
            message.get("text")
            or message.get("message")
            or message.get("content")
            or message.get("output")
            or str(message)
        )

        self._emit_event(event_kind, message_text, message)

    def _emit_event(
        self,
        event_kind: str,
        message: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a canonical event through the underlying sink."""
        details: dict[str, Any] = {"extractor": "opencode-ndjson"}
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


def build_opencode_stream_sinks(
    *,
    packet_ctx: dict[str, Any],
    stream_controls: dict[str, Any] | None = None,
) -> tuple[list[StreamSink], list[StreamSink]]:
    """Build opencode-specific stream sinks with NDJSON event extraction.

    This adds OpencodeEventExtractor on top of the standard sinks to parse
    opencode NDJSON events into canonical events.
    """
    # Build base sinks
    stdout_sinks, stderr_sinks = build_provider_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    # Find the NormalizedEventSink for stdout and wrap it with OpencodeEventExtractor
    job_id = packet_ctx.get("job-id")
    for i, sink in enumerate(stdout_sinks):
        if isinstance(sink, NormalizedEventSink):
            # Replace with OpencodeEventExtractor that wraps the original sink
            stdout_sinks[i] = OpencodeEventExtractor(
                event_sink=sink,
                job_id=job_id,
                provider_id="opencode",
            )
            break

    return stdout_sinks, stderr_sinks


def _build_prompt(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> str:
    prompt_body = packet_ctx.get("prompt-body")
    prompt = (
        "AUDiaGentic opencode provider execution request. "
        f"job={packet_ctx.get('job-id')} "
        f"packet={packet_ctx.get('packet-id')} "
        f"provider={packet_ctx.get('provider-id', 'opencode')} "
        f"model={provider_cfg.get('default-model')} "
        f"workflow={packet_ctx.get('workflow-profile')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible."
    )
    if prompt_body:
        prompt += f" Prompt body: {str(prompt_body).strip()}"
    return prompt.strip()


def _opencode_executable() -> str:
    executable = shutil.which("opencode")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-011",
            kind="external",
            message="opencode command is not available on PATH",
            details={"provider-id": "opencode"},
        )
    return executable


def _parse_opencode_completion(
    stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
    """Parse opencode completion from NDJSON stdout.

    opencode outputs NDJSON with events like:
    {"type":"text","part":{"text":"..."}}
    {"type":"step_finish","sessionID":"..."}

    Returns:
        tuple[dict[str, Any] | None, ResultSource]: (parsed_data, source)
    """
    completion_data: dict[str, Any] = {}
    session_id: str | None = None
    text_parts: list[str] = []

    for line in stdout.splitlines():
        payload = line.strip()
        if not payload:
            continue
        try:
            message = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue

        # Extract session ID
        session_value = (
            message.get("sessionID")
            or message.get("sessionId")
            or message.get("session")
        )
        if session_id is None and session_value is not None:
            session_id = str(session_value)

        # Extract text from part object (opencode format)
        part = message.get("part", {})
        if isinstance(part, dict):
            part_text = part.get("text", "")
            if isinstance(part_text, str) and part_text.strip():
                text_parts.append(part_text.strip())

        # Also check top-level fields for compatibility
        candidate = (
            message.get("text")
            or message.get("message")
            or message.get("content")
            or message.get("output")
        )
        if isinstance(candidate, str) and candidate.strip():
            text_parts.append(candidate.strip())

    # Combine text parts
    if text_parts:
        completion_data["kind"] = "adhoc"
        completion_data["completion_text"] = " ".join(text_parts)
        completion_data["session_id"] = session_id
        return completion_data, ResultSource.STDOUT_JSON

    extracted = try_extract_json_from_stdout(stdout)
    if extracted:
        if "kind" not in extracted:
            extracted["kind"] = "adhoc"
        return extracted, ResultSource.STDOUT_JSON_BLOCK

    return None, ResultSource.STDOUT_TEXT


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _opencode_executable()
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = provider_cfg.get("default-model")
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    execution_policy = provider_cfg.get("execution-policy", {})
    output_format = execution_policy.get("output-format", "json")

    command = [executable, "run", "--format", str(output_format)]
    if default_model:
        command.extend(["--model", str(default_model)])
    command.append(prompt)

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_opencode_stream_sinks(
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

    # Parse structured completion
    parsed_data, result_source = _parse_opencode_completion(
        stdout_text, stderr_text, completed.returncode
    )

    output_text = stdout_text
    session_id = None
    if parsed_data:
        output_text = parsed_data.get("completion_text", output_text)
        session_id = parsed_data.get("session_id")

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-012",
            kind="external",
            message="opencode execution failed",
            details={
                "provider-id": "opencode",
                "returncode": completed.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "command": command,
            },
        )

    # Build canonical completion
    if parsed_data and result_source != ResultSource.STDOUT_TEXT:
        completion = normalize_provider_result(
            provider_id="opencode",
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
            provider_id="opencode",
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
        "provider-id": packet_ctx.get("provider-id", "opencode"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "session-id": session_id,
        "output": output_text or stdout_text,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "returncode": completed.returncode,
        "command": command,
        "completion": completion.to_dict(),
    }
