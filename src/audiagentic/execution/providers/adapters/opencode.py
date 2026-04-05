"""opencode provider adapter."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.streaming.provider_streaming import build_provider_stream_sinks, run_streaming_command


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


def _parse_output(stdout: str) -> tuple[str, str | None]:
    completion_text = ""
    session_id: str | None = None

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

        session_value = message.get("sessionID") or message.get("sessionId") or message.get("session")
        if session_id is None and session_value is not None:
            session_id = str(session_value)

        candidate = (
            message.get("text")
            or message.get("message")
            or message.get("content")
            or message.get("output")
        )
        if isinstance(candidate, str) and candidate.strip():
            completion_text = candidate.strip()

    return completion_text, session_id


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _opencode_executable()
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = provider_cfg.get("default-model")
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    command = [executable, "run", "--format", "json"]
    if default_model:
        command.extend(["--model", str(default_model)])
    command.append(prompt)

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_provider_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )
    completed = run_streaming_command(
        command,
        cwd=cwd,
        stdout_sinks=stdout_sinks,
        stderr_sinks=stderr_sinks,
    )

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    output_text, session_id = _parse_output(stdout)

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-012",
            kind="external",
            message="opencode execution failed",
            details={
                "provider-id": "opencode",
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "command": command,
            },
        )

    return {
        "provider-id": packet_ctx.get("provider-id", "opencode"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "session-id": session_id,
        "output": output_text or stdout,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": completed.returncode,
        "command": command,
    }
