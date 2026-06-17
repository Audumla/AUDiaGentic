"""opencode provider adapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.optional.providers.adapters.cli import require_executable
from audiagentic.components.optional.providers.protocols.streaming.base_extractor import (
    BaseEventExtractor,
)
from audiagentic.components.optional.providers.protocols.streaming.completion import (
    NormalizationMethod,
    ResultSource,
    build_synthetic_fallback,
    normalize_provider_result,
    persist_completion,
    try_extract_json_from_stdout,
)
from audiagentic.components.optional.providers.protocols.streaming.provider_streaming import (
    build_extractor_stream_sinks,
    run_streaming_command,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


class OpencodeEventExtractor(BaseEventExtractor):
    """Parse opencode NDJSON events into canonical provider-stream-event records."""

    extractor_name = "opencode-ndjson"

    EVENT_KIND_MAP = {
        "session.started": "task-start",
        "assistant.message": "task-progress",
        "tool.call": "tool-call",
        "tool.result": "tool-result",
        "error": "error",
        "session.complete": "completion",
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
        message_text = (
            message.get("text")
            or message.get("message")
            or message.get("content")
            or message.get("output")
            or str(message)
        )
        self._emit_event(event_kind, message_text, message)


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


def _parse_opencode_completion(
    stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
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

        session_value = (
            message.get("sessionID")
            or message.get("sessionId")
            or message.get("session")
        )
        if session_id is None and session_value is not None:
            session_id = str(session_value)

        part = message.get("part", {})
        if isinstance(part, dict):
            part_text = part.get("text", "")
            if isinstance(part_text, str) and part_text.strip():
                text_parts.append(part_text.strip())

        candidate = (
            message.get("text")
            or message.get("message")
            or message.get("content")
            or message.get("output")
        )
        if isinstance(candidate, str) and candidate.strip():
            text_parts.append(candidate.strip())

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
    executable = require_executable("opencode", "opencode")
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
    stdout_sinks, stderr_sinks = build_extractor_stream_sinks(
        OpencodeEventExtractor,
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
            code="EXT-OPENC-001",
            kind="providers",
            message="opencode execution failed",
            details={
                "provider-id": "opencode",
                "returncode": completed.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "command": command,
            },
        )

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

    working_root_path = Path(working_root) if working_root else None
    if working_root_path and packet_ctx.get("job-id"):
        try:
            persist_completion(working_root_path, packet_ctx.get("job-id"), completion)
        except AudiaGenticError:
            logger.warning("Failed to persist completion", exc_info=True)

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
