"""Claude provider adapter."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError


def _find_packet_doc(working_root: str | None, packet_id: str | None) -> Path | None:
    if not working_root or not packet_id:
        return None
    packet_name = str(packet_id).upper()
    packets_root = Path(working_root) / "docs" / "implementation" / "packets"
    if not packets_root.exists():
        return None
    for path in packets_root.rglob(f"{packet_name}.md"):
        if path.is_file():
            return path
    return None


def _packet_doc_excerpt(path: Path, *, max_lines: int = 80) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[:max_lines]).strip()


def _build_prompt(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> str:
    packet_doc = _find_packet_doc(packet_ctx.get("working-root"), packet_ctx.get("packet-id"))
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
    lines = [
        "AUDiaGentic Claude provider execution request.",
        "Use the packet document excerpt as the task definition.",
        "Do not ask for follow-up details unless the packet context is unusable.",
        "Carry out the requested work or, if execution is impossible, report the blocking reason and the next concrete step.",
        json.dumps(envelope, indent=2, sort_keys=True),
    ]
    if packet_doc is not None:
        lines.extend(["", "Packet document excerpt:", _packet_doc_excerpt(packet_doc)])
    if prompt_body:
        lines.extend(["", "Prompt body:", str(prompt_body).strip()])
    return "\n".join(lines).strip()


def _claude_executable() -> str:
    executable = shutil.which("claude")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-003",
            kind="external",
            message="claude command is not available on PATH",
            details={"provider-id": "claude"},
        )
    return executable


def _run_claude(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=input_text,
    )


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _claude_executable()
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = provider_cfg.get("default-model")
    permission_mode = provider_cfg.get("permission-mode", "auto")
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None
    command = [
        executable,
        "--print",
        "--output-format",
        "text",
        "--permission-mode",
        str(permission_mode),
    ]
    if default_model:
        command.extend(["--model", str(default_model)])

    completed = _run_claude(command, cwd=cwd, input_text=prompt)
    output_text = completed.stdout.strip()

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-004",
            kind="external",
            message="claude execution failed",
            details={
                "provider-id": "claude",
                "returncode": completed.returncode,
                "stdout": (completed.stdout or "").strip(),
                "stderr": (completed.stderr or "").strip(),
                "command": command,
            },
        )

    return {
        "provider-id": packet_ctx.get("provider-id", "claude"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "output": output_text,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
        "returncode": completed.returncode,
        "command": command,
    }
