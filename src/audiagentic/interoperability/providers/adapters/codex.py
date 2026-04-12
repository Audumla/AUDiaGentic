"""Codex provider adapter."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.interoperability.protocols.streaming.completion import (
    NormalizationMethod,
    ResultSource,
    build_synthetic_fallback,
    normalize_provider_result,
    persist_completion,
    try_extract_json_from_stdout,
)
from audiagentic.interoperability.protocols.streaming.provider_streaming import (
    build_provider_stream_sinks,
    run_streaming_command,
)
from audiagentic.interoperability.protocols.streaming.sinks import NormalizedEventSink, StreamSink


class CodexEventExtractor:
    """Extract Codex milestone events from stream output.

    This sink parses Codex wrapper milestone lines and translates them into
    canonical provider-stream-event records before forwarding to NormalizedEventSink.
    """

    # Patterns for Codex milestone lines
    MILESTONE_PATTERNS = {
        "task-start": re.compile(
            r"^\[MILESTONE\]\s*task-start:\s*(.+)$", re.IGNORECASE
        ),
        "task-progress": re.compile(
            r"^\[MILESTONE\]\s*task-progress:\s*(.+)$", re.IGNORECASE
        ),
        "task-complete": re.compile(
            r"^\[MILESTONE\]\s*task-complete:\s*(.+)$", re.IGNORECASE
        ),
        "error": re.compile(r"^\[ERROR\]\s*(.+)$", re.IGNORECASE),
    }

    def __init__(
        self,
        event_sink: NormalizedEventSink,
        job_id: str | None = None,
        provider_id: str = "codex",
    ) -> None:
        self.event_sink = event_sink
        self.job_id = job_id
        self.provider_id = provider_id

    def write(self, line: str) -> None:
        """Process a line and extract Codex events."""
        text = line.rstrip("\r\n")
        if not text:
            return

        # Check for milestone patterns
        for event_kind, pattern in self.MILESTONE_PATTERNS.items():
            match = pattern.match(text)
            if match:
                message = match.group(1).strip()
                self._emit_event(event_kind, message)
                return

        # Pass through non-milestone lines as task-progress
        self._emit_event("task-progress", text)

    def _emit_event(self, event_kind: str, message: str) -> None:
        """Emit a canonical event through the underlying sink."""
        self.event_sink.write_event(
            {
                "contract-version": "v1",
                "job-id": self.job_id,
                "provider-id": self.provider_id,
                "event-kind": event_kind,
                "message": message,
                "timestamp": _utc_now(),
                "details": {"extractor": "codex-milestone"},
            }
        )

    def flush(self) -> None:
        self.event_sink.flush()

    def close(self) -> None:
        self.event_sink.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_codex_stream_sinks(
    *,
    packet_ctx: dict[str, Any],
    stream_controls: dict[str, Any] | None = None,
) -> tuple[list[StreamSink], list[StreamSink]]:
    """Build Codex-specific stream sinks with event extraction.

    This adds CodexEventExtractor on top of the standard sinks to parse
    Codex milestone lines into canonical events.
    """
    # Build base sinks
    stdout_sinks, stderr_sinks = build_provider_stream_sinks(
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    # Find the NormalizedEventSink for stdout and wrap it with CodexEventExtractor
    job_id = packet_ctx.get("job-id")
    for i, sink in enumerate(stdout_sinks):
        if isinstance(sink, NormalizedEventSink):
            # Replace with CodexEventExtractor that wraps the original sink
            stdout_sinks[i] = CodexEventExtractor(
                event_sink=sink,
                job_id=job_id,
                provider_id="codex",
            )
            break

    return stdout_sinks, stderr_sinks


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
    """Parse Codex completion from last message or stdout.

    Returns:
        tuple[dict[str, Any] | None, ResultSource]: (parsed_data, source)
    """
    # Try to parse last_message as JSON
    if last_message:
        try:
            data = json.loads(last_message)
            if isinstance(data, dict):
                if "kind" not in data:
                    data = {"kind": "adhoc", **data}
                return data, ResultSource.RESULT_FILE
        except json.JSONDecodeError:
            pass

    # Try to parse stdout as JSON
    if stdout:
        try:
            data = json.loads(stdout)
            if isinstance(data, dict):
                if "kind" not in data:
                    data = {"kind": "adhoc", **data}
                return data, ResultSource.STDOUT_JSON
        except json.JSONDecodeError:
            pass

    # Try to extract JSON block from stdout
    extracted = try_extract_json_from_stdout(stdout)
    if extracted:
        if "kind" not in extracted:
            extracted = {"kind": "adhoc", **extracted}
        return extracted, ResultSource.STDOUT_JSON_BLOCK

    return None, ResultSource.STDOUT_TEXT


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

    execution_policy = provider_cfg.get("execution-policy", {})
    ephemeral = bool(execution_policy.get("ephemeral", True))
    full_auto = bool(execution_policy.get("full-auto", True))

    fd, last_message_path = tempfile.mkstemp(
        prefix="codex-last-message-", suffix=".txt"
    )
    os.close(fd)
    output_path = Path(last_message_path)
    command = [
        executable,
        "exec",
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_path),
    ]
    if ephemeral:
        command.insert(2, "--ephemeral")
    if full_auto:
        command.insert(3, "--full-auto")
    if default_model:
        command.extend(["--model", str(default_model)])
    command.append(prompt)

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_codex_stream_sinks(
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

    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()
    output_text = last_message or stdout_text

    # Parse structured completion
    parsed_data, result_source = _parse_codex_completion(
        last_message, stdout_text, stderr_text, completed.returncode
    )

    # Build canonical completion
    if parsed_data and result_source != ResultSource.STDOUT_TEXT:
        completion = normalize_provider_result(
            provider_id="codex",
            job_id=packet_ctx.get("job-id"),
            prompt_id=packet_ctx.get("prompt-id"),
            surface=packet_ctx.get("surface"),
            stage=packet_ctx.get("workflow-profile"),
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=completed.returncode,
            result_source=result_source,
            normalization_method=NormalizationMethod.PROVIDER_NATIVE_JSON,
            subject=parsed_data,
        )
    else:
        completion = build_synthetic_fallback(
            provider_id="codex",
            job_id=packet_ctx.get("job-id"),
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=completed.returncode,
        )

    # Persist completion
    working_root_path = Path(working_root) if working_root else None
    if working_root_path and packet_ctx.get("job-id"):
        try:
            persist_completion(working_root_path, packet_ctx.get("job-id"), completion)
        except AudiaGenticError:
            pass

    return {
        "provider-id": packet_ctx.get("provider-id", "codex"),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": default_model,
        "output": output_text,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "returncode": completed.returncode,
        "command": command,
        "completion": completion.to_dict(),
    }
