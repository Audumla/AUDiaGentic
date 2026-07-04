"""Shared YAML-driven provider execution pipeline (AR12).

Providers whose descriptor carries an ``execution:`` block run through this
generic pipeline: resolve executable → build prompt → build command from the
declared args template → stream → parse completion → normalize. Adapters keep
a hand-written ``adapter.py`` only for genuinely custom behavior (codex
packet-doc excerpts, gemini prompt tags, claude/local_openai streaming);
services/execution.py prefers an adapter module and falls back here.

``execution:`` block schema:
  mode: cli | stub | ok-stub | unsupported   (default cli)
  executable: display id passed to require_executable   (cli/stub)
  aliases: [binary names to try, in order]               (cli/stub)
  prompt-title: title used in the default prompt preamble (cli)
  error-code: canonical error code (cli failure / unsupported)
  args-template: list of tokens after the executable; "{prompt}",
      "{approval-flags}" and "{model-flags}" expand, other tokens pass
      through with "{model}" formatting applied  (cli)
  model-flag: flag emitted before the model for "{model-flags}"  (cli)
  approval-mode-flags: map of execution-policy permission-mode → flag list
  message: stub / unsupported message text
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters._stubs import make_ok_stub, make_probe_stub
from audiagentic.components.providers.adapters.cli import require_executable
from audiagentic.components.providers.protocols.streaming.base_extractor import (
    BaseEventExtractor,
)
from audiagentic.components.providers.protocols.streaming.completion import (
    NormalizationMethod,
    ResultSource,
    build_synthetic_fallback,
    normalize_provider_result,
    persist_completion,
    try_extract_json_from_stdout,
)
from audiagentic.components.providers.protocols.streaming.provider_streaming import (
    build_extractor_stream_sinks,
    run_streaming_command,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)

ProviderRunner = Any  # Callable[[dict, dict], dict] — mirrors services.execution


def make_plaintext_extractor(name: str) -> type[BaseEventExtractor]:
    """Extractor emitting one task-progress event per output line.

    Parses JSON lines into structured payloads when possible — the behavior
    previously copy-pasted as <Provider>EventExtractor per adapter.
    """
    class _PlainTextEventExtractor(BaseEventExtractor):
        extractor_name = name

        def write(self, line: str) -> None:
            text = line.rstrip("\r\n")
            if not text:
                return
            try:
                message = json.loads(text)
                if isinstance(message, dict):
                    self._emit_event("task-progress", text, message)
                else:
                    self._emit_event("task-progress", text)
            except json.JSONDecodeError:
                self._emit_event("task-progress", text)

    return _PlainTextEventExtractor


def default_build_prompt(
    packet_ctx: dict[str, Any],
    provider_cfg: dict[str, Any],
    *,
    provider_id: str,
    title: str,
) -> str:
    prompt_body = packet_ctx.get("prompt-body")
    prompt = (
        f"AUDiaGentic {title} provider execution request. "
        f"job={packet_ctx.get('job-id')} "
        f"packet={packet_ctx.get('packet-id')} "
        f"provider={packet_ctx.get('provider-id', provider_id)} "
        f"model={provider_cfg.get('default-model')} "
        f"workflow={packet_ctx.get('workflow-profile')}. "
        "Return a concise execution summary or the blocking reason if execution is impossible."
    )
    if prompt_body:
        prompt += f" Prompt body: {str(prompt_body).strip()}"
    return prompt.strip()


def default_parse_completion(
    stdout: str, stderr: str, returncode: int
) -> tuple[dict[str, Any] | None, ResultSource]:
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            return data, ResultSource.STDOUT_JSON
    except (json.JSONDecodeError, ValueError):
        pass

    extracted = try_extract_json_from_stdout(stdout)
    if extracted:
        return extracted, ResultSource.STDOUT_JSON_BLOCK

    return None, ResultSource.STDOUT_TEXT


def _build_command(
    executable: str,
    execution: dict[str, Any],
    *,
    prompt: str,
    model: str | None,
    approval_mode: str,
) -> list[str]:
    command = [executable]
    template = execution.get("args-template") or ["{approval-flags}", "{model-flags}", "{prompt}"]
    for token in template:
        if token == "{approval-flags}":
            command.extend(
                (execution.get("approval-mode-flags") or {}).get(approval_mode, [])
            )
        elif token == "{model-flags}":
            model_flag = execution.get("model-flag")
            if model and model_flag:
                command.extend([model_flag, str(model)])
        elif token == "{prompt}":
            command.append(prompt)
        elif "{model}" in token:
            if model:
                command.append(token.format(model=model))
        else:
            command.append(token)
    return command


def finalize_run(
    *,
    provider_id: str,
    packet_ctx: dict[str, Any],
    provider_cfg: dict[str, Any],
    command: list[str],
    stdout_text: str,
    stderr_text: str,
    returncode: int,
    parsed_data: dict[str, Any] | None,
    result_source: ResultSource,
    output_text: str | None = None,
    extra_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize, persist, and shape a provider run result.

    The post-stream tail previously copy-pasted across every substantial
    adapter: normalize the parsed completion (or build the synthetic
    fallback), persist it under the job dir, and assemble the standard result
    payload. ``extra_result`` carries provider-specific keys (task-id,
    session-id, ...).
    """
    if parsed_data and result_source != ResultSource.STDOUT_TEXT:
        completion = normalize_provider_result(
            provider_id=provider_id,
            job_id=packet_ctx.get("job-id"),
            prompt_id=packet_ctx.get("prompt-id"),
            surface=packet_ctx.get("surface"),
            stage=packet_ctx.get("workflow-profile"),
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=returncode,
            result_source=result_source,
            normalization_method=NormalizationMethod.PROVIDER_NATIVE_JSON,
            subject=parsed_data,
        )
    else:
        completion = build_synthetic_fallback(
            provider_id=provider_id,
            job_id=packet_ctx.get("job-id"),
            stdout=stdout_text,
            stderr=stderr_text,
            returncode=returncode,
        )

    working_root = packet_ctx.get("working-root")
    working_root_path = Path(working_root) if working_root else None
    if working_root_path and packet_ctx.get("job-id"):
        try:
            persist_completion(working_root_path, packet_ctx.get("job-id"), completion)
        except AudiaGenticError:
            logger.warning("Failed to persist completion", exc_info=True)

    result = {
        "provider-id": packet_ctx.get("provider-id", provider_id),
        "status": "ok",
        "execution-mode": provider_cfg.get("access-mode", "cli"),
        "model": provider_cfg.get("default-model"),
        "output": output_text if output_text is not None else stdout_text,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "returncode": returncode,
        "command": command,
        "completion": completion.to_dict(),
    }
    if extra_result:
        result.update(extra_result)
    return result


def make_cli_runner(
    provider_id: str,
    execution: dict[str, Any],
    *,
    build_prompt=None,
    parse_completion=None,
    extractor_cls: type[BaseEventExtractor] | None = None,
):
    """Build the generic CLI run() previously copy-pasted per adapter."""
    title = execution.get("prompt-title", provider_id)
    error_code = execution.get("error-code", f"EXT-{provider_id.upper().replace('-', '')[:8]}-001")
    aliases = tuple(execution.get("aliases") or (provider_id,))
    exec_name = execution.get("executable", provider_id)
    parse = parse_completion or default_parse_completion
    extractor = extractor_cls or make_plaintext_extractor(
        execution.get("extractor-name", f"{provider_id}-plaintext")
    )

    def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
        executable = require_executable(exec_name, *aliases)
        if build_prompt is not None:
            prompt = build_prompt(packet_ctx, provider_cfg)
        else:
            prompt = default_build_prompt(
                packet_ctx, provider_cfg, provider_id=provider_id, title=title
            )
        default_model = provider_cfg.get("default-model")
        working_root = packet_ctx.get("working-root")
        cwd = Path(working_root) if working_root else None

        execution_policy = provider_cfg.get("execution-policy", {})
        approval_mode = execution_policy.get("permission-mode", "auto")

        command = _build_command(
            executable,
            execution,
            prompt=prompt,
            model=default_model,
            approval_mode=approval_mode,
        )

        stream_controls = packet_ctx.get("stream-controls", {})
        stdout_sinks, stderr_sinks = build_extractor_stream_sinks(
            extractor,
            packet_ctx=packet_ctx,
            stream_controls=stream_controls,
        )

        completed = run_streaming_command(
            command,
            cwd=cwd,
            stdout_sinks=stdout_sinks,
            stderr_sinks=stderr_sinks,
        )
        stdout_text = completed.stdout.strip()
        stderr_text = completed.stderr.strip()

        if completed.returncode != 0:
            raise AudiaGenticError(
                code=error_code,
                kind="providers",
                message=f"{provider_id} execution failed",
                details={
                    "provider-id": provider_id,
                    "returncode": completed.returncode,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "command": command,
                },
            )

        parsed_data, result_source = parse(stdout_text, stderr_text, completed.returncode)

        return finalize_run(
            provider_id=provider_id,
            packet_ctx=packet_ctx,
            provider_cfg=provider_cfg,
            command=command,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            returncode=completed.returncode,
            parsed_data=parsed_data,
            result_source=result_source,
        )

    return run


def _make_unsupported_runner(provider_id: str, execution: dict[str, Any]):
    code = execution.get("error-code", f"CON-{provider_id.upper().replace('-', '')[:8]}-001")
    message = execution.get("message", f"{provider_id} has no CLI execution adapter")

    def run(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> dict[str, Any]:
        raise AudiaGenticError(
            code=code,
            kind="providers",
            message=message,
            details={"provider-id": provider_id},
        )

    return run


def make_runner_from_execution(provider_id: str, execution: dict[str, Any]):
    """Build a runner from a descriptor's ``execution:`` block."""
    mode = execution.get("mode", "cli")
    if mode == "cli":
        return make_cli_runner(provider_id, execution)
    if mode == "stub":
        aliases = tuple(execution.get("aliases") or (provider_id,))
        return make_probe_stub(
            provider_id,
            *aliases,
            message=execution.get("message", f"{provider_id} adapter is registered; execution bridge not wired yet."),
        )
    if mode == "ok-stub":
        return make_ok_stub(provider_id)
    if mode == "unsupported":
        return _make_unsupported_runner(provider_id, execution)
    raise AudiaGenticError(
        code="VAL-EXEC-001",
        kind="providers",
        message=f"unknown execution mode {mode!r} for provider {provider_id!r}",
        details={"provider-id": provider_id, "mode": mode},
    )
