"""Codex provider adapter."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.providers.streaming import run_streaming_command


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
    excerpt = lines[:max_lines]
    return "\n".join(excerpt).strip()


def _build_prompt(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> str:
    prompt_body = packet_ctx.get("prompt-body")
    packet_doc = _find_packet_doc(packet_ctx.get("working-root"), packet_ctx.get("packet-id"))
    envelope = {
        "job-id": packet_ctx.get("job-id"),
        "provider-id": packet_ctx.get("provider-id", "codex"),
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
        "AUDiaGentic Codex provider execution request.",
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


def _codex_executable() -> str:
    executable = shutil.which("codex")
    if executable is None:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-001",
            kind="external",
            message="codex command is not available on PATH",
            details={"provider-id": "codex"},
        )
    return executable


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = _codex_executable()
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = provider_cfg.get("default-model")
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    fd, last_message_path = tempfile.mkstemp(prefix="codex-last-message-", suffix=".txt")
    os.close(fd)
    output_path = Path(last_message_path)
    command = [
        executable,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--full-auto",
        "--output-last-message",
        str(output_path),
    ]
    if default_model:
        command.extend(["--model", str(default_model)])
    command.append(prompt)

    runtime_root = None
    job_id = packet_ctx.get("job-id")
    if working_root and job_id:
        runtime_root = Path(working_root) / ".audiagentic" / "runtime" / "jobs" / str(job_id)
    stream_controls = packet_ctx.get("stream-controls", {})
    tee_console = bool(stream_controls.get("tee-console", False)) or bool(stream_controls.get("enabled", False))
    stdout_log = runtime_root / "stdout.log" if runtime_root is not None else None
    stderr_log = runtime_root / "stderr.log" if runtime_root is not None else None

    try:
        completed = run_streaming_command(
            command,
            cwd=cwd,
            stdout_log_path=stdout_log,
            stderr_log_path=stderr_log,
            tee_console=tee_console,
        )
        last_message = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="PRV-EXTERNAL-002",
            kind="external",
            message="codex execution failed",
            details={
                "provider-id": "codex",
                "returncode": completed.returncode,
                "stdout": (completed.stdout or "").strip(),
                "stderr": (completed.stderr or "").strip(),
                "command": command,
            },
        )

    output_text = last_message or (completed.stdout or "").strip()
    return {
        "provider-id": packet_ctx.get("provider-id", "codex"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "output": output_text,
        "stdout": (completed.stdout or "").strip(),
        "stderr": (completed.stderr or "").strip(),
        "returncode": completed.returncode,
        "command": command,
    }
