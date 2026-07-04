"""Cline provider adapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.base_runner import default_build_prompt, finalize_run
from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.components.providers.protocols.streaming.base_extractor import (
    BaseEventExtractor,
)
from audiagentic.components.providers.protocols.streaming.completion import (
    ResultSource,
    try_extract_json_from_stdout,
)
from audiagentic.components.providers.protocols.streaming.provider_streaming import (
    build_extractor_stream_sinks,
    run_streaming_command,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


class ClineEventExtractor(BaseEventExtractor):
    """Parse Cline NDJSON events into canonical provider-stream-event records."""

    extractor_name = "cline-ndjson"

    EVENT_KIND_MAP = {
        "task_started": "task-start",
        "task_progress": "task-progress",
        "task_complete": "task-complete",
        "completion_result": "completion",
        "tool_call": "tool-call",
        "tool_result": "tool-result",
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

        event_type = message.get("type") or message.get("say")
        event_kind = self.EVENT_KIND_MAP.get(event_type, "task-progress")
        message_text = message.get("text") or message.get("message") or str(message)

        self._emit_event(event_kind, message_text, message)




def _parse_cline_completion(
    stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
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

        if task_id is None and message.get("type") == "task_started":
            task_id = (
                str(message.get("taskId"))
                if message.get("taskId") is not None
                else None
            )

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
    executable = require_executable("cline", "cline")
    prompt = default_build_prompt(packet_ctx, provider_cfg, provider_id="cline", title="Cline")
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
    stdout_sinks, stderr_sinks = build_extractor_stream_sinks(
        ClineEventExtractor,
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
            code="EXT-CLINE-001",
            kind="providers",
            message="cline execution failed",
            details={
                "provider-id": "cline",
                "returncode": completed.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "command": command,
            },
        )

    return finalize_run(
        provider_id="cline",
        packet_ctx=packet_ctx,
        provider_cfg=provider_cfg,
        command=command,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        returncode=completed.returncode,
        parsed_data=parsed_data,
        result_source=result_source,
        output_text=output_text or stdout_text,
        extra_result={"task-id": task_id},
    )
