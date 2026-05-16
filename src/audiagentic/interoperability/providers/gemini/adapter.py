"""Gemini provider adapter."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.execution.jobs.prompt_launch import launch_prompt_request
from audiagentic.execution.jobs.prompt_parser import parse_prompt_launch_request
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


class GeminiEventExtractor:
    """Extract Gemini events from stream output.

    This sink parses Gemini plain-text output and translates it into canonical
    provider-stream-event records before forwarding to NormalizedEventSink.
    """

    def __init__(
        self,
        event_sink: NormalizedEventSink,
        job_id: str | None = None,
        provider_id: str = "gemini",
    ) -> None:
        self.event_sink = event_sink
        self.job_id = job_id
        self.provider_id = provider_id

    def write(self, line: str) -> None:
        """Process a line and extract Gemini events."""
        text = line.rstrip("\r\n")
        if not text:
            return

        # Try to parse as JSON for future -o json support
        try:
            message = json.loads(text)
            if isinstance(message, dict):
                # For future JSON-format support, map event types here
                # For now, all JSON events and text are task-progress
                self._emit_event("task-progress", text, message)
            else:
                self._emit_event("task-progress", text)
        except json.JSONDecodeError:
            # Plain text line (Gemini uses -o text)
            self._emit_event("task-progress", text)

    def _emit_event(
        self,
        event_kind: str,
        message: str,
        raw_payload: dict[str, Any] | None = None,
    ) -> None:
        """Emit a canonical event through the underlying sink."""
        details: dict[str, Any] = {"extractor": "gemini-plaintext"}
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


def build_gemini_stream_sinks(
    *,
    packet_ctx: dict[str, Any],
    stream_controls: dict[str, Any] | None = None,
) -> tuple[list[StreamSink], list[StreamSink]]:
    """Build Gemini-specific stream sinks with event extraction.

    This adds GeminiEventExtractor on top of the standard sinks to parse
    Gemini output into canonical events.
    """
    # Build base sinks
    stdout_sinks, stderr_sinks = build_provider_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    # Find the NormalizedEventSink for stdout and wrap it with GeminiEventExtractor
    job_id = packet_ctx.get("job-id")
    for i, sink in enumerate(stdout_sinks):
        if isinstance(sink, NormalizedEventSink):
            # Replace with GeminiEventExtractor that wraps the original sink
            stdout_sinks[i] = GeminiEventExtractor(
                event_sink=sink,
                job_id=job_id,
                provider_id="gemini",
            )
            break

    return stdout_sinks, stderr_sinks


def _handle_prompt_tags(
    packet_ctx: dict[str, Any],
    provider_cfg: dict[str, Any],
    working_root: Path,
) -> tuple[str | None, str | None]:
    """Handle canonical prompt tags if present.

    Returns:
        tuple[str | None, str | None]: (modified_prompt, job_id)
    """
    prompt_text = packet_ctx.get("prompt-body")
    if not prompt_text:
        return None, None

    # Detect first non-empty line
    lines = prompt_text.splitlines()
    first_non_empty = None
    for line in lines:
        if line.strip():
            first_non_empty = line.strip()
            break

    if not first_non_empty or not first_non_empty.startswith("@"):
        return None, None

    # Parse tag
    try:
        request = parse_prompt_launch_request(
            prompt_text,
            surface=packet_ctx.get("surface", "cli"),
            provider_id=packet_ctx.get("provider-id", "gemini"),
            session_id=packet_ctx.get("session-id"),
            model_id=packet_ctx.get("model-id"),
            model_alias=packet_ctx.get("model-alias"),
            workflow_profile=packet_ctx.get("workflow-profile", "standard"),
            allow_adhoc_target=True,
        )
        result = launch_prompt_request(working_root, request)
        if result.get("status") in {"created", "resumed", "complete"}:
            # Return the modified prompt (without tag line) and the job-id
            return request.get("prompt-body", "").strip(), result.get("job-id")
    except AudiaGenticError:
        # If parsing fails, we let it pass through to the provider unless it's a hard error
        pass

    return None, None


def _build_prompt(
    packet_ctx: dict[str, Any],
    provider_cfg: dict[str, Any],
    modified_prompt: str | None = None,
) -> str:
    prompt_body = modified_prompt or packet_ctx.get("prompt-body")
    prompt = (
        "AUDiaGentic Gemini provider execution request. "
        f"job={packet_ctx.get('job-id')} "
        f"packet={packet_ctx.get('packet-id')} "
        f"provider={packet_ctx.get('provider-id', 'gemini')} "
        f"model={provider_cfg.get('default-model')} "
        f"workflow={packet_ctx.get('workflow-profile')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible."
    )
    if prompt_body:
        prompt += f" Prompt body: {str(prompt_body).strip()}"
    return prompt.strip()


def _parse_gemini_completion(
    stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
    """Parse Gemini completion from stdout.

    Returns:
        tuple[dict[str, Any] | None, ResultSource]: (parsed_data, source)
    """
    # Try to parse stdout as JSON
    if stdout:
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                if "kind" not in data:
                    data = {"kind": "adhoc", **data}
                return data, ResultSource.STDOUT_JSON
        except json.JSONDecodeError:
            pass

    extracted = try_extract_json_from_stdout(stdout)
    if extracted:
        if "kind" not in extracted:
            extracted["kind"] = "adhoc"
        return extracted, ResultSource.STDOUT_JSON_BLOCK

    return None, ResultSource.STDOUT_TEXT


def _gemini_executable() -> str:
    executable = shutil.which("gemini")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-005",
            kind="external",
            message="gemini command is not available on PATH",
            details={"provider-id": "gemini"},
        )
    return executable


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _gemini_executable()
    working_root_str = packet_ctx.get("working-root")
    working_root = Path(working_root_str) if working_root_str else Path.cwd()

    modified_prompt, job_id = _handle_prompt_tags(
        packet_ctx, provider_cfg, working_root
    )
    if job_id:
        packet_ctx["job-id"] = job_id

    prompt = _build_prompt(packet_ctx, provider_cfg, modified_prompt=modified_prompt)
    default_model = provider_cfg.get("default-model")
    cwd = working_root

    execution_policy = provider_cfg.get("execution-policy", {})
    output_format = execution_policy.get("output-format", "text")
    safety_mode = execution_policy.get("safety-mode", "standard")

    command = [
        executable,
        "-p",
        prompt,
        "-o",
        str(output_format),
    ]
    if safety_mode == "relaxed":
        command.append("--yolo")
    if default_model:
        command.extend(["-m", str(default_model)])

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_gemini_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    completed = run_streaming_command(
        command,
        cwd=cwd,
        stdout_sinks=stdout_sinks,
        stderr_sinks=stderr_sinks,
    )
    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-006",
            kind="external",
            message="gemini execution failed",
            details={
                "provider-id": "gemini",
                "returncode": completed.returncode,
                "stdout": (completed.stdout or "").strip(),
                "stderr": (completed.stderr or "").strip(),
                "command": command,
            },
        )

    stdout_text = completed.stdout.strip()
    stderr_text = (completed.stderr or "").strip()
    output_text = stdout_text

    # Parse structured completion
    parsed_data, result_source = _parse_gemini_completion(
        stdout_text, stderr_text, completed.returncode
    )

    # Build canonical completion
    if parsed_data and result_source != ResultSource.STDOUT_TEXT:
        completion = normalize_provider_result(
            provider_id="gemini",
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
            provider_id="gemini",
            job_id=packet_ctx.get("job-id"),
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=completed.returncode,
        )

    # Persist completion
    working_root_path = Path(working_root_str) if working_root_str else None
    if working_root_path and packet_ctx.get("job-id"):
        try:
            persist_completion(working_root_path, packet_ctx.get("job-id"), completion)
        except AudiaGenticError:
            pass

    return {
        "provider-id": packet_ctx.get("provider-id", "gemini"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "output": output_text,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "returncode": completed.returncode,
        "command": command,
        "job-id": packet_ctx.get("job-id"),
        "completion": completion.to_dict(),
    }
