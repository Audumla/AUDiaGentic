"""Qwen provider adapter."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError


def _build_prompt(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> str:
    prompt_body = packet_ctx.get("prompt-body")
    prompt = (
        "AUDiaGentic Qwen provider execution request. "
        f"job={packet_ctx.get('job-id')} "
        f"packet={packet_ctx.get('packet-id')} "
        f"provider={packet_ctx.get('provider-id', 'qwen')} "
        f"model={provider_cfg.get('default-model')} "
        f"workflow={packet_ctx.get('workflow-profile')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible."
    )
    if prompt_body:
        prompt += f" Prompt body: {str(prompt_body).strip()}"
    return prompt.strip()


def _qwen_executable() -> str:
    executable = shutil.which("qwen")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-007",
            kind="external",
            message="qwen command is not available on PATH",
            details={"provider-id": "qwen"},
        )
    return executable


def _run_qwen(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
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
    executable = _qwen_executable()
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = provider_cfg.get("default-model")
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    command = [
        executable,
        "-p",
        prompt,
        "-o",
        "text",
    ]
    if default_model:
        command.extend(["-m", str(default_model)])

    completed = _run_qwen(command, cwd=cwd)
    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-008",
            kind="external",
            message="qwen execution failed",
            details={
                "provider-id": "qwen",
                "returncode": completed.returncode,
                "stdout": (completed.stdout or "").strip(),
                "stderr": (completed.stderr or "").strip(),
                "command": command,
            },
        )

    output_text = (completed.stdout or "").strip()
    return {
        "provider-id": packet_ctx.get("provider-id", "qwen"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "output": output_text,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
        "returncode": completed.returncode,
        "command": command,
    }
