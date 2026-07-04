"""Gemini provider adapter."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.base_runner import finalize_run
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

try:
    from audiagentic.components.agent_jobs.prompt_launch import launch_prompt_request
    from audiagentic.components.agent_jobs.prompt_parser import parse_prompt_launch_request
except ImportError:
    launch_prompt_request = None  # type: ignore[assignment]
    parse_prompt_launch_request = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class GeminiEventExtractor(BaseEventExtractor):
    """Parse Gemini plain-text output into canonical provider-stream-event records."""

    extractor_name = "gemini-plaintext"

    def write(self, line: str) -> None:
        text = line.rstrip("\r\n")
        if not text:
            return
        try:
            message = json.loads(text)
            if isinstance(message, dict):
                self._emit_event("task-progress", text, message)
            else:
                self._emit_event("task-progress", text)
        except json.JSONDecodeError:
            self._emit_event("task-progress", text)


def _handle_prompt_tags(
    packet_ctx: dict[str, Any],
    provider_cfg: dict[str, Any],
    working_root: Path,
) -> tuple[str | None, str | None]:
    if parse_prompt_launch_request is None or launch_prompt_request is None:
        return None, None
    prompt_text = packet_ctx.get("prompt-body")
    if not prompt_text:
        return None, None

    lines = prompt_text.splitlines()
    first_non_empty = None
    for line in lines:
        if line.strip():
            first_non_empty = line.strip()
            break

    if not first_non_empty or not first_non_empty.startswith("@"):
        return None, None

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
            return request.get("prompt-body", "").strip(), result.get("job-id")
    except AudiaGenticError:
        logger.warning("Prompt tag parsing failed, proceeding with original prompt", exc_info=True)

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


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = require_executable("gemini", "gemini")
    working_root_str = packet_ctx.get("working-root")
    working_root = Path(working_root_str) if working_root_str else Path.cwd()

    modified_prompt, job_id = _handle_prompt_tags(packet_ctx, provider_cfg, working_root)
    if job_id:
        packet_ctx["job-id"] = job_id

    prompt = _build_prompt(packet_ctx, provider_cfg, modified_prompt=modified_prompt)
    default_model = provider_cfg.get("default-model")
    cwd = working_root

    execution_policy = provider_cfg.get("execution-policy", {})
    output_format = execution_policy.get("output-format", "text")
    safety_mode = execution_policy.get("safety-mode", "standard")

    command = [executable, "-p", prompt, "-o", str(output_format)]
    if safety_mode == "relaxed":
        command.append("--yolo")
    if default_model:
        command.extend(["-m", str(default_model)])

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_extractor_stream_sinks(
        GeminiEventExtractor,
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
            code="EXT-GEMINI-001",
            kind="providers",
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

    parsed_data, result_source = _parse_gemini_completion(
        stdout_text, stderr_text, completed.returncode
    )

    return finalize_run(
        provider_id="gemini",
        packet_ctx=packet_ctx,
        provider_cfg=provider_cfg,
        command=command,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        returncode=completed.returncode,
        parsed_data=parsed_data,
        result_source=result_source,
        output_text=output_text,
        extra_result={"job-id": packet_ctx.get("job-id")},
    )
