"""Pi provider execution adapter — pipes prompt via stdin to preserve newlines.

SH21 root cause: when Pi's --print mode receives the prompt as a CLI argument,
embedded newlines are lost during Pi's internal argument processing (the first
newline acts as a separator or is stripped). The fix pipes the full prompt
through stdin instead of as a CLI argument — Pi reads piped stdin in --print
mode and preserves its content intact.

This adapter overrides the YAML-driven runner only for one-shot execution;
live ACP sessions use adapters/pi/acp.py and are unaffected.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.base_runner import (
    default_parse_completion,
    finalize_run,
    make_plaintext_extractor,
    resolve_execution_model,
)
from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.components.providers.protocols.streaming.provider_streaming import (
    build_extractor_stream_sinks,
    run_streaming_command,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

# Reuse the same extraction as the YAML descriptor.
extractor = make_plaintext_extractor("pi-plaintext")
parse = default_parse_completion


def _build_command(
    executable: str,
    *,
    model: str | None,
) -> list[str]:
    """Build the Pi command WITHOUT the prompt argument — stdin delivers it.

    SH21: the prompt is piped via stdin (run_streaming_command input_text) to
    avoid newline loss in Pi's --print argument processing.
    """
    command = [executable, "--print"]
    if model:
        command.extend(["--model", model])
    return command


def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
    """Execute Pi via stdin-piped --print mode.

    Prompt delivery via stdin instead of CLI argument to preserve embedded
    newlines (SH21 — first-newline loss in Pi's --print arg processing).
    """
    executable = require_executable("pi", "pi")
    prompt_body = packet_ctx.get("prompt-body") or ""
    default_model = resolve_execution_model(packet_ctx, provider_cfg)

    working_root = packet_ctx.get("working-root")
    cwd = Path(working_root) if working_root else None

    command = _build_command(executable, model=default_model)

    stream_controls = packet_ctx.get("stream-controls", {})
    stdout_sinks, stderr_sinks = build_extractor_stream_sinks(
        extractor,
        packet_ctx=packet_ctx,
        stream_controls=stream_controls,
    )

    completed = run_streaming_command(
        command,
        cwd=cwd,
        input_text=prompt_body,  # SH21 fix: pipe prompt via stdin
        stdout_sinks=stdout_sinks,
        stderr_sinks=stderr_sinks,
    )
    stdout_text = completed.stdout.strip()
    stderr_text = completed.stderr.strip()

    if completed.returncode != 0:
        raise AudiaGenticError(
            code="EXT-PI-001",
            kind="providers",
            message="pi execution failed",
            details={
                "provider-id": "pi",
                "returncode": completed.returncode,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "command": command,
            },
        )

    parsed_data, result_source = parse(stdout_text, stderr_text, completed.returncode)

    return finalize_run(
        provider_id="pi",
        packet_ctx=packet_ctx,
        provider_cfg=provider_cfg,
        command=command,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        returncode=completed.returncode,
        parsed_data=parsed_data,
        result_source=result_source,
    )
