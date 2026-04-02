"""Gemini provider adapter."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.execution.jobs.prompt_launch import launch_prompt_request
from audiagentic.execution.jobs.prompt_parser import parse_prompt_launch_request


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


def _build_prompt(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any], modified_prompt: str | None = None) -> str:
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


def _run_gemini(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _gemini_executable()
    working_root_str = packet_ctx.get("working-root")
    working_root = Path(working_root_str) if working_root_str else Path.cwd()

    modified_prompt, job_id = _handle_prompt_tags(packet_ctx, provider_cfg, working_root)
    if job_id:
        packet_ctx["job-id"] = job_id

    prompt = _build_prompt(packet_ctx, provider_cfg, modified_prompt=modified_prompt)
    default_model = provider_cfg.get("default-model")
    cwd = working_root

    command = [
        executable,
        "-p",
        prompt,
        "-o",
        "text",
        "--yolo",
    ]
    if default_model:
        command.extend(["-m", str(default_model)])

    completed = _run_gemini(command, cwd=cwd)
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

    output_text = (completed.stdout or "").strip()
    return {
        "provider-id": packet_ctx.get("provider-id", "gemini"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "output": output_text,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
        "returncode": completed.returncode,
        "command": command,
        "job-id": packet_ctx.get("job-id"),
    }
