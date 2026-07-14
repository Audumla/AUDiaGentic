"""Codex provider adapter."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.base_runner import (
    finalize_run,
    resolve_execution_model,
)
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


class CodexEventExtractor(BaseEventExtractor):
    """Parse Codex milestone lines into canonical provider-stream-event records."""

    extractor_name = "codex-milestone"

    MILESTONE_PATTERNS = {
        "task-start": re.compile(r"^\[MILESTONE\]\s*task-start:\s*(.+)$", re.IGNORECASE),
        "task-progress": re.compile(r"^\[MILESTONE\]\s*task-progress:\s*(.+)$", re.IGNORECASE),
        "task-complete": re.compile(r"^\[MILESTONE\]\s*task-complete:\s*(.+)$", re.IGNORECASE),
        "error": re.compile(r"^\[ERROR\]\s*(.+)$", re.IGNORECASE),
    }

    def write(self, line: str) -> None:
        text = line.rstrip("\r\n")
        if not text:
            return
        for event_kind, pattern in self.MILESTONE_PATTERNS.items():
            match = pattern.match(text)
            if match:
                self._emit_event(event_kind, match.group(1).strip())
                return
        self._emit_event("task-progress", text)


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
    prompt_body = packet_ctx.get("prompt-body")
    packet_doc = _find_packet_doc(
        packet_ctx.get("working-root"), packet_ctx.get("packet-id")
    )
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


def _parse_codex_completion(
    last_message: str, stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
    if last_message:
        try:
            data = json.loads(last_message)
            if isinstance(data, dict):
                if "kind" not in data:
                    data = {"kind": "adhoc", **data}
                return data, ResultSource.RESULT_FILE
        except json.JSONDecodeError:
            pass

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
            extracted = {"kind": "adhoc", **extracted}
        return extracted, ResultSource.STDOUT_JSON_BLOCK

    return None, ResultSource.STDOUT_TEXT


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = require_executable("codex", "codex")
    prompt = _build_prompt(packet_ctx, provider_cfg)
    default_model = resolve_execution_model(packet_ctx, provider_cfg)
    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    execution_policy = provider_cfg.get("execution-policy", {})
    full_auto = bool(execution_policy.get("full-auto", True))

    fd, last_message_path = tempfile.mkstemp(prefix="codex-last-message-", suffix=".txt")
    os.close(fd)
    output_path = Path(last_message_path)
    command = [
        executable,
        "exec",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_path),
    ]
    if full_auto:
        command.insert(2, "--full-auto")
    if default_model:
        command.extend(["--model", str(default_model)])
    command.append(prompt)

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_extractor_stream_sinks(
        CodexEventExtractor,
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    try:
        completed = run_streaming_command(
            command,
            cwd=cwd,
            stdout_sinks=stdout_sinks,
            stderr_sinks=stderr_sinks,
        )
        last_message = (
            output_path.read_text(encoding="utf-8").strip()
            if output_path.exists()
            else ""
        )
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="EXT-CODEX-001",
            kind="providers",
            message="codex execution failed",
            details={
                "provider-id": "codex",
                "returncode": completed.returncode,
                "stdout": (completed.stdout or "").strip(),
                "stderr": (completed.stderr or "").strip(),
                "command": command,
            },
        )

    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    output_text = last_message or stdout_text

    parsed_data, result_source = _parse_codex_completion(
        last_message, stdout_text, stderr_text, completed.returncode
    )

    return finalize_run(
        provider_id="codex",
        packet_ctx=packet_ctx,
        provider_cfg=provider_cfg,
        command=command,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        returncode=completed.returncode,
        parsed_data=parsed_data,
        result_source=result_source,
        output_text=output_text,
    )
