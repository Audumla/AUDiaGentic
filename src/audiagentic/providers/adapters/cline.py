"""Cline provider adapter."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError


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


def _run_cline(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _parse_output(stdout: str) -> tuple[str, str | None]:
    completion_text = ""
    task_id: str | None = None

    for line in stdout.splitlines():
        payload = line.strip()
        if not payload:
            continue
        try:
            message = json.loads(payload)
        except json.JSONDecodeError:
            continue

        if isinstance(message, dict):
            if task_id is None and message.get("type") == "task_started":
                task_id = str(message.get("taskId")) if message.get("taskId") is not None else None
            if message.get("type") == "completion_result" or message.get("say") == "completion_result":
                completion_text = str(message.get("text") or "").strip()

    return completion_text, task_id


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _cline_executable()
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = provider_cfg.get("default-model")
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    command = [
        executable,
        "--json",
        "--auto-approve-all",
    ]
    if cwd is not None:
        command.extend(["--cwd", str(cwd)])
    if default_model:
        command.extend(["--model", str(default_model)])
    command.append(prompt)

    completed = _run_cline(command, cwd=cwd)
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    output_text, task_id = _parse_output(stdout)

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-010",
            kind="external",
            message="cline execution failed",
            details={
                "provider-id": "cline",
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "command": command,
            },
        )

    return {
        "provider-id": packet_ctx.get("provider-id", "cline"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "task-id": task_id,
        "output": output_text or stdout,
        "stdout": stdout,
        "stderr": stderr,
        "returncode": completed.returncode,
        "command": command,
    }
