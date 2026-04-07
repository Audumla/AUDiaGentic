"""Claude provider adapter."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError
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


class ClaudeEventExtractor:
    """Extract Claude events from stream output.

    This sink parses Claude JSON stream events (when --output-format stream-json is used)
    and translates them into canonical provider-stream-event records before forwarding
    to NormalizedEventSink.
    """

    # Claude event type to canonical event kind mapping
    EVENT_KIND_MAP = {
        "message_start": "task-start",
        "content_block_start": "task-progress",
        "content_block_delta": "task-progress",
        "content_block_stop": "task-progress",
        "message_delta": "task-progress",
        "message_stop": "completion",
        "error": "error",
    }

    def __init__(
        self,
        event_sink: NormalizedEventSink,
        job_id: str | None = None,
        provider_id: str = "claude",
    ) -> None:
        self.event_sink = event_sink
        self.job_id = job_id
        self.provider_id = provider_id

    def write(self, line: str) -> None:
        """Process a line and extract Claude events."""
        text = line.rstrip("\r\n")
        if not text:
            return

        # Try to parse as JSON stream-json format
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            # Plain text line (when using --output-format text)
            self._emit_event("task-progress", text)
            return

        if not isinstance(message, dict):
            self._emit_event("task-progress", text)
            return

        # Extract event type
        event_type = message.get("type")
        event_kind = self.EVENT_KIND_MAP.get(event_type, "task-progress")

        # Extract message content based on event type
        message_text = text
        if event_type == "content_block_delta":
            delta = message.get("delta", {})
            if delta.get("type") == "text_delta":
                message_text = delta.get("text", "")
        elif event_type == "message_delta":
            delta = message.get("delta", {})
            message_text = delta.get("stop_reason", "message_delta")
        elif event_type == "message_start":
            message_text = "message_start"

        self._emit_event(event_kind, message_text, message)

    def _emit_event(
        self,
        event_kind: str,
        message: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a canonical event through the underlying sink."""
        details: dict[str, Any] = {"extractor": "claude-stream-json"}
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


def build_claude_stream_sinks(
    *,
    packet_ctx: dict[str, Any],
    stream_controls: dict[str, Any] | None = None,
) -> tuple[list[StreamSink], list[StreamSink]]:
    """Build Claude-specific stream sinks with JSON event extraction.

    This adds ClaudeEventExtractor on top of the standard sinks to parse
    Claude JSON stream events into canonical events.
    """
    # Build base sinks
    stdout_sinks, stderr_sinks = build_provider_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    # Find the NormalizedEventSink for stdout and wrap it with ClaudeEventExtractor
    job_id = packet_ctx.get("job-id")
    for i, sink in enumerate(stdout_sinks):
        if isinstance(sink, NormalizedEventSink):
            # Replace with ClaudeEventExtractor that wraps the original sink
            stdout_sinks[i] = ClaudeEventExtractor(
                event_sink=sink,
                job_id=job_id,
                provider_id="claude",
            )
            break

    return stdout_sinks, stderr_sinks


def _find_packet_doc(working_root: str | None, packet_id: str | None) -> Path | None:
    if not working_root or not packet_id:
        return None
    packet_name = str(packet_id).upper()
    packets_root = Path(working_root) / "docs" / "implementation" / "packets"
    if not packets_root.exists():
        return None
    for path in packets_root.rglob(f"{packet_name}.md"):
        if path.is_file():
            return path
    return None


def _packet_doc_excerpt(path: Path, *, max_lines: int = 80) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:max_lines]).strip()


def _build_prompt(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> str:
    packet_doc = _find_packet_doc(
        packet_ctx.get("working-root"), packet_ctx.get("packet-id")
    )
    prompt_body = packet_ctx.get("prompt-body")
    envelope = {
        "job-id": packet_ctx.get("job-id"),
        "provider-id": packet_ctx.get("provider-id", "claude"),
        "packet-id": packet_ctx.get("packet-id"),
        "project-id": packet_ctx.get("project-id"),
        "workflow-profile": packet_ctx.get("workflow-profile"),
        "model-id": packet_ctx.get("model-id"),
        "model-alias": packet_ctx.get("model-alias"),
        "default-model": provider_cfg.get("default-model"),
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "surface": packet_ctx.get("surface", "cli"),
    }
    if packet_doc is not None:
        envelope["packet-doc-path"] = str(packet_doc)
    lines = [
        "AUDiaGentic Claude provider execution request.",
        "Use the packet document excerpt as the task definition.",
        "Do not ask for follow-up details unless the packet context is unusable.",
        "Carry out the requested work or, if execution is impossible, report the blocking reason and the next concrete step.",
        json.dumps(envelope, indent=2, sort_keys=True),
    ]
    if packet_doc is not None:
        lines.extend(["", "Packet document excerpt:", _packet_doc_excerpt(packet_doc)])
    if prompt_body:
        lines.extend(["", "Prompt body:", str(prompt_body).strip()])
    return "\n".join(lines).strip()


def _parse_claude_completion(
    stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
    """Parse Claude completion from stdout.

    Returns:
        tuple[dict[str, Any] | None, ResultSource]: (parsed_data, source)
    """
    # Try to parse stdout as JSON directly
    if stdout:
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                if "kind" not in data:
                    data = {"kind": "adhoc", **data}
                return data, ResultSource.STDOUT_JSON
        except json.JSONDecodeError:
            pass

    # Try to extract JSON block from markdown stdout
    extracted = try_extract_json_from_stdout(stdout)
    if extracted:
        if "kind" not in extracted:
            extracted = {"kind": "adhoc", **extracted}
        return extracted, ResultSource.STDOUT_JSON_BLOCK

    return None, ResultSource.STDOUT_TEXT


def _claude_executable() -> str:
    executable = shutil.which("claude")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-003",
            kind="external",
            message="claude command is not available on PATH",
            details={"provider-id": "claude"},
        )
    return executable


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _claude_executable()
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = provider_cfg.get("default-model")
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    execution_policy = provider_cfg.get("execution-policy", {})
    output_format = execution_policy.get("output-format", "text")
    permission_mode = execution_policy.get("permission-mode", "auto")

    command = [
        executable,
        "--print",
        "--output-format",
        str(output_format),
        "--permission-mode",
        str(permission_mode),
    ]
    if default_model:
        command.extend(["--model", str(default_model)])

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_claude_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )
    completed = run_streaming_command(
        command,
        cwd=cwd,
        input_text=prompt,
        stdout_sinks=stdout_sinks,
        stderr_sinks=stderr_sinks,
    )
    stdout_text = completed.stdout.strip()
    stderr_text = (completed.stderr or "").strip()
    output_text = stdout_text

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-004",
            kind="external",
            message="claude execution failed",
            details={
                "provider-id": "claude",
                "returncode": completed.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "command": command,
            },
        )

    # Parse structured completion
    parsed_data, result_source = _parse_claude_completion(
        stdout_text, stderr_text, completed.returncode
    )

    # Build canonical completion
    if parsed_data and result_source != ResultSource.STDOUT_TEXT:
        completion = normalize_provider_result(
            provider_id="claude",
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
            provider_id="claude",
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
        "provider-id": packet_ctx.get("provider-id", "claude"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "output": output_text,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "returncode": completed.returncode,
        "command": command,
        "completion": completion.to_dict(),
    }
