"""GitHub Copilot provider adapter compatibility seam."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.base_runner import (
    default_build_prompt,
    default_parse_completion,
    finalize_run,
    make_plaintext_extractor,
)
from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.components.providers.protocols.streaming.provider_streaming import (
    build_extractor_stream_sinks,
    run_streaming_command,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    executable = require_executable("copilot", "gh")
    prompt = default_build_prompt(
        packet_ctx,
        provider_cfg,
        provider_id="copilot",
        title="Copilot",
    )
    command = [executable, "copilot", "suggest", "-t", "shell", prompt]

    working_root = packet_ctx.get("working-root")
    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_extractor_stream_sinks(
        make_plaintext_extractor("copilot-plaintext"),
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )
    completed = run_streaming_command(
        command,
        cwd=Path(working_root) if working_root else None,
        stdout_sinks=stdout_sinks,
        stderr_sinks=stderr_sinks,
    )
    stdout_text = (completed.stdout or "").strip()
    stderr_text = (completed.stderr or "").strip()

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="EXT-COPIL-001",
            kind="providers",
            message="copilot execution failed",
            details={
                "provider-id": "copilot",
                "returncode": completed.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "command": command,
            },
        )

    parsed_data, result_source = default_parse_completion(
        stdout_text,
        stderr_text,
        completed.returncode,
    )
    return finalize_run(
        provider_id="copilot",
        packet_ctx=packet_ctx,
        provider_cfg=provider_cfg,
        command=command,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        returncode=completed.returncode,
        parsed_data=parsed_data,
        result_source=result_source,
    )
