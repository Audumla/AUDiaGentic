"""Cline provider adapter."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.interoperability.protocols.streaming.completion import (
    NormalizationMethod,
    ResultSource,
    build_synthetic_fallback,
    normalize_provider_result,
    persist_completion,
    try_extract_json_from_stdout,
)
from audiagentic.interoperability.protocols.streaming.provider_streaming import (
    build_provider_stream_sinks,
    run_streaming_command,
)
from audiagentic.interoperability.protocols.streaming.sinks import NormalizedEventSink, StreamSink


class ClineEventExtractor:
    """Extract Cline NDJSON events from stream output.

    This sink parses Cline native NDJSON task-progress events and translates them into
    canonical provider-stream-event records before forwarding to NormalizedEventSink.
    """

    # Cline event type to canonical event kind mapping
    EVENT_KIND_MAP = {
        "task_started": "task-start",
        "task_progress": "task-progress",
        "task_complete": "task-complete",
        "completion_result": "completion",
        "tool_call": "tool-call",
        "tool_result": "tool-result",
        "error": "error",
    }

    def __init__(
        self,
        event_sink: NormalizedEventSink,
        job_id: str | None = None,
        provider_id: str = "cline",
    ) -> None:
        self.event_sink = event_sink
        self.job_id = job_id
        self.provider_id = provider_id

    def write(self, line: str) -> None:
        """Process a line and extract Cline NDJSON events."""
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
        event_type = message.get("type") or message.get("say")
        event_kind = self.EVENT_KIND_MAP.get(event_type, "task-progress")

        # Extract message content
        message_text = message.get("text") or message.get("message") or str(message)

        self._emit_event(event_kind, message_text, message)

    def _emit_event(
        self,
        event_kind: str,
        message: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a canonical event through the underlying sink."""
        details: dict[str, Any] = {"extractor": "cline-ndjson"}
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


def build_cline_stream_sinks(
    *,
    packet_ctx: dict[str, Any],
    stream_controls: dict[str, Any] | None = None,
) -> tuple[list[StreamSink], list[StreamSink]]:
    """Build Cline-specific stream sinks with NDJSON event extraction.

    This adds ClineEventExtractor on top of the standard sinks to parse
    Cline NDJSON events into canonical events.
    """
    # Build base sinks
    stdout_sinks, stderr_sinks = build_provider_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    # Find the NormalizedEventSink for stdout and wrap it with ClineEventExtractor
    job_id = packet_ctx.get("job-id")
    for i, sink in enumerate(stdout_sinks):
        if isinstance(sink, NormalizedEventSink):
            # Replace with ClineEventExtractor that wraps the original sink
            stdout_sinks[i] = ClineEventExtractor(
                event_sink=sink,
                job_id=job_id,
                provider_id="cline",
            )
            break

    return stdout_sinks, stderr_sinks


def _build_prompt(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> str:
    prompt_body = packet_ctx.get("prompt-body")
    prompt = (
        "AUDiaGentic Cline provider execution request. "
        f"job={packet_ctx.get('job-id')} "
        f"packet={packet_ctx.get('packet-id')} "
        f"provider={packet_ctx.get('provider-id', 'cline')} "
        f"model={provider_cfg.get('default-model')} "
        f"workflow={packet_ctx.get('workflow-profile')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible."
    )
    if prompt_body:
        prompt += f" Prompt body: {str(prompt_body).strip()}"
    return prompt.strip()


def _cline_executable() -> str:
    executable = shutil.which("cline")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-009",
            kind="external",
            message="cline command is not available on PATH",
            details={"provider-id": "cline"},
        )
    return executable


def _parse_cline_completion(
    stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
    """Parse Cline completion from NDJSON stdout.

    Returns:
        tuple[dict[str, Any] | None, ResultSource]: (parsed_data, source)
    """
    completion_data: dict[str, Any] = {}
    task_id: str | None = None
    has_structured_data = False

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

        # Extract task_id
        if task_id is None and message.get("type") == "task_started":
            task_id = (
                str(message.get("taskId"))
                if message.get("taskId") is not None
                else None
            )

        # Extract completion_result
        if (
            message.get("type") == "completion_result"
            or message.get("say") == "completion_result"
        ):
            completion_data["kind"] = "adhoc"
            completion_data["completion_text"] = str(message.get("text") or "").strip()
            completion_data["task_id"] = task_id
            has_structured_data = True

    if has_structured_data:
        return completion_data, ResultSource.STDOUT_JSON

    extracted = try_extract_json_from_stdout(stdout)
    if extracted:
        if "kind" not in extracted:
            extracted["kind"] = "adhoc"
        return extracted, ResultSource.STDOUT_JSON_BLOCK

    return None, ResultSource.STDOUT_TEXT


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _cline_executable()
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = provider_cfg.get("default-model")
    timeout_seconds = provider_cfg.get("timeout-seconds", 60)
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    execution_policy = provider_cfg.get("execution-policy", {})
    output_format = execution_policy.get("output-format", "json")
    auto_approve = bool(execution_policy.get("auto-approve", True))

    command = [executable]
    if output_format == "json":
        command.append("--json")
    if auto_approve:
        command.append("--auto-approve-all")
    if timeout_seconds:
        command.extend(["--timeout", str(timeout_seconds)])
    if cwd is not None:
        command.extend(["--cwd", str(cwd)])
    if default_model:
        command.extend(["--model", str(default_model)])
    command.append(prompt)

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_cline_stream_sinks(
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
    parsed_data, result_source = _parse_cline_completion(
        stdout_text, stderr_text, completed.returncode
    )

    output_text = stdout_text
    task_id = None
    if parsed_data:
        output_text = parsed_data.get("completion_text", output_text)
        task_id = parsed_data.get("task_id")

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-010",
            kind="external",
            message="cline execution failed",
            details={
                "provider-id": "cline",
                "returncode": completed.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "command": command,
            },
        )

    # Build canonical completion
    if parsed_data and result_source != ResultSource.STDOUT_TEXT:
        completion = normalize_provider_result(
            provider_id="cline",
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
            provider_id="cline",
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
        "provider-id": packet_ctx.get("provider-id", "cline"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "task-id": task_id,
        "output": output_text or stdout_text,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "returncode": completed.returncode,
        "command": command,
        "completion": completion.to_dict(),
    }
