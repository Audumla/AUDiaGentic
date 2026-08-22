"""Claude provider adapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.base_runner import resolve_execution_model
from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.components.providers.protocols.streaming.base_extractor import (
    BaseEventExtractor,
)
from audiagentic.components.providers.protocols.streaming.completion import (
    NormalizationMethod,
    ResultSource,
    build_synthetic_fallback,
    normalize_provider_result,
    persist_completion,
    try_extract_json_from_stdout,
)
from audiagentic.components.providers.protocols.streaming.provider_streaming import (
    build_extractor_stream_sinks,
    run_streaming_command,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


class ClaudeEventExtractor(BaseEventExtractor):
    """Parse Claude JSON stream events into canonical provider-stream-event records."""

    extractor_name = "claude-stream-json"

    EVENT_KIND_MAP = {
        "message_start": "task-start",
        "content_block_start": "task-progress",
        "content_block_delta": "task-progress",
        "content_block_stop": "task-progress",
        "message_delta": "task-progress",
        "message_stop": "completion",
        "error": "error",
    }

    def write(self, line: str) -> None:
        text = line.rstrip("\r\n")
        if not text:
            return
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            self._emit_event("task-progress", text)
            return

        if not isinstance(message, dict):
            self._emit_event("task-progress", text)
            return

        event_type = message.get("type")
        event_kind = self.EVENT_KIND_MAP.get(event_type, "task-progress")

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


def _packet_doc_excerpt(working_root: str | None, packet_id: str | None) -> str | None:
    if not working_root or not packet_id:
        return None
    packet_name = str(packet_id).upper()
    packets_root = Path(working_root) / "docs" / "implementation" / "packets"
    if not packets_root.exists():
        return None
    for path in packets_root.rglob(f"{packet_name}.md"):
        if path.is_file():
            return "\n".join(path.read_text().splitlines()[:80]).strip()
    return None


def _build_prompt(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> str:
    from audiagentic.components.providers.providers_api import build_admitted_agent_prompt
    packet_doc = _packet_doc_excerpt(
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
    lines = [build_admitted_agent_prompt(packet_ctx, provider_cfg, provider_id="claude", title="Claude")]
    lines.extend(["Provider packet context:", json.dumps(envelope, indent=2, sort_keys=True)])
    if packet_doc is not None:
        lines.extend(["", "Packet document excerpt:", packet_doc])
    if prompt_body:
        lines.extend(["", "Prompt body:", str(prompt_body).strip()])
    return "\n".join(lines).strip()


def _ensure_kind(data: dict[str, Any]) -> dict[str, Any]:
    if "kind" not in data:
        return {"kind": "adhoc", **data}
    return data


def _parse_claude_completion(
    stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
    if stdout:
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                return _ensure_kind(data), ResultSource.STDOUT_JSON
        except json.JSONDecodeError:
            pass

    extracted = try_extract_json_from_stdout(stdout)
    if extracted:
        return _ensure_kind(extracted), ResultSource.STDOUT_JSON_BLOCK

    return None, ResultSource.STDOUT_TEXT


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = require_executable("claude", "claude")
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = resolve_execution_model(packet_ctx, provider_cfg)
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None
    job_id = packet_ctx.get("job-id")
    prompt_id = packet_ctx.get("prompt-id")
    surface = packet_ctx.get("surface")

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
    stdout_sinks, stderr_sinks = build_extractor_stream_sinks(
        ClaudeEventExtractor,
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

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="EXT-CLAUDE-001",
            kind="providers",
            message="claude execution failed",
            details={
                "provider-id": "claude",
                "returncode": completed.returncode,
                "stdout-length": len(stdout_text),
                "stderr-length": len(stderr_text),
                "command": command,
            },
        )

    parsed_data, result_source = _parse_claude_completion(
        stdout_text, stderr_text, completed.returncode
    )

    if parsed_data and result_source != ResultSource.STDOUT_TEXT:
        completion = normalize_provider_result(
            provider_id="claude",
            job_id=job_id,
            prompt_id=prompt_id,
            surface=surface,
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
            job_id=job_id,
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=completed.returncode,
        )

    working_root_path = Path(working_root) if working_root else None
    if working_root_path and job_id:
        try:
            persist_completion(working_root_path, job_id, completion)
        except AudiaGenticError:
            logger.warning("Failed to persist completion", exc_info=True)

    return {
        "provider-id": packet_ctx.get("provider-id", "claude"),
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
