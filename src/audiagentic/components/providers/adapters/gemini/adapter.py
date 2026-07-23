"""Gemini provider adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.base_runner import (
    finalize_run,
    make_plaintext_extractor,
    resolve_execution_model,
)
from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.components.providers.prompt_tags import parse_tagged_prompt
from audiagentic.components.providers.protocols.streaming.completion import (
    ResultSource,
    try_extract_json_from_stdout,
)
from audiagentic.components.providers.protocols.streaming.provider_streaming import (
    build_extractor_stream_sinks,
    run_streaming_command,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

GeminiEventExtractor = make_plaintext_extractor("gemini-plaintext")


def _handle_prompt_tags(
    packet_ctx: dict[str, Any],
) -> str | None:
    prompt_text = packet_ctx.get("prompt-body")
    if not isinstance(prompt_text, str):
        return None
    tagged_prompt = parse_tagged_prompt(prompt_text)
    return tagged_prompt.body.strip() if tagged_prompt is not None else None


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
        f"model={resolve_execution_model(packet_ctx, provider_cfg)} "
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
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    modified_prompt = _handle_prompt_tags(packet_ctx)

    prompt = _build_prompt(packet_ctx, provider_cfg, modified_prompt=modified_prompt)
    default_model = resolve_execution_model(packet_ctx, provider_cfg)

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
