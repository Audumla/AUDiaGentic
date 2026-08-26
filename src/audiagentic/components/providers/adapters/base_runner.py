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
      through with "{model}" formatting applied  (cli); if the resolved
      template omits {prompt}, the built prompt is piped via
      run_streaming_command's input_text instead — the prompt always reaches
      the process one way or the other; there is no separate delivery flag
      to set
  model-flag: flag emitted before the model for "{model-flags}"  (cli)
  approval-mode-flags: map of execution-policy permission-mode → flag list
  message: stub / unsupported message text
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
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
from audiagentic.foundation.transports import ProviderLaunch


def _config_path(config: dict[str, Any], dotted_key: str) -> Any:
    """Resolve a dotted config key (``tools.mode``) or None if any hop misses."""
    node: Any = config
    for part in dotted_key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _resolve_arg_token(
    token: Any,
    spec_decl: dict[str, Any],
    context: dict[str, Any],
    config: dict[str, Any],
) -> list[str]:
    """Resolve one args entry to zero or more argv strings.

    Vocabulary shared by every launch kind. String tokens cover the launch
    context (prompt, model, mcp surface, runner args); dict tokens are
    config-driven flag primitives (enum-flags, value-flag, repeat-value-flag,
    boolean-flags). No conditionals beyond these declarative primitives.
    """
    model = context.get("model")

    if isinstance(token, dict):
        if "enum-flags" in token:
            decl = token["enum-flags"]
            value = _config_path(config, decl["key"])
            cases = decl.get("cases") or {}
            if value is None and "default" in decl:
                value = decl["default"]
            return list(cases.get(value, []))
        if "value-flag" in token:
            decl = token["value-flag"]
            value = _config_path(config, decl["key"])
            if value in (None, "", [], {}):
                return []
            if isinstance(value, (list, tuple)):
                value = decl.get("join", ",").join(str(v) for v in value)
            return [decl["flag"], str(value)]
        if "repeat-value-flag" in token:
            decl = token["repeat-value-flag"]
            values = _config_path(config, decl["key"]) or []
            out: list[str] = []
            for item in values:
                out.extend([decl["flag"], str(item)])
            return out
        if "boolean-flags" in token:
            decl = token["boolean-flags"]
            default = decl.get("default", False)
            out = []
            for key, flag in (decl.get("flags") or {}).items():
                resolved = _config_path(config, key)
                enabled = default if resolved is None else bool(resolved)
                if enabled:
                    out.append(flag)
            return out
        raise AudiaGenticError(
            code="VAL-EXEC-003",
            kind="providers",
            message="unknown launch arg primitive",
            details={"token": sorted(token.keys())},
        )

    # --- string tokens ---
    if token == "{prompt}":
        return [context["prompt"]] if context.get("prompt") is not None else []
    if token == "{approval-flags}":
        return list((spec_decl.get("approval-mode-flags") or {}).get(context.get("approval-mode", "auto"), []))
    if token == "{model-flags}":
        model_flag = spec_decl.get("model-flag")
        return [model_flag, str(model)] if model and model_flag else []
    if token == "{mcp-args}":
        return list(context.get("mcp-args", ()))
    if token == "{runner-args}":
        return list(context.get("runner-args", ()))
    if "{model}" in token:
        return [token.format(model=model)] if model else []
    return [token]


def _resolve_environment(env_decl: Any, context: dict[str, Any]) -> dict[str, str]:
    """Build the launch environment from a static env block + context.

    Env values may reference ``{key}`` placeholders resolved from
    ``context['env']`` (a flat str map). ``context['extra-env']`` (e.g. the
    MCP surface's env) is merged on top.
    """
    environment: dict[str, str] = {}
    env_context: dict[str, str] = context.get("env", {})
    for name, value_template in (env_decl or {}).items():
        environment[name] = str(value_template).format(**env_context)
    environment.update(context.get("extra-env", {}))
    return environment


def build_launch_spec(
    spec_decl: dict[str, Any],
    *,
    context: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> ProviderLaunch:
    """Build a normalized :class:`ProviderLaunch` from a declarative recipe.

    The one shared spec builder for every launch kind (one-shot execution,
    ACP, interactive). ``spec_decl`` declares ``executable``/``aliases``, an
    ``args`` (or legacy ``args-template``) list over the token vocabulary in
    :func:`_resolve_arg_token`, and an optional ``environment`` block.
    ``context`` carries per-launch resolved substitutions; ``config`` is the
    provider CLI config consulted by config-driven flag primitives. Pure data
    transformation — resolves the executable on PATH but never spawns.
    """
    context = context or {}
    config = config or {}

    exec_name = spec_decl.get("executable") or ""
    aliases = tuple(spec_decl.get("aliases") or ((exec_name,) if exec_name else ()))
    executable = require_executable(exec_name or (aliases[0] if aliases else ""), *aliases)

    template = spec_decl.get("args-template") or spec_decl.get("args")
    if template is None:
        template = ["{approval-flags}", "{model-flags}", "{prompt}"]
    args: list[str] = []
    for token in template:
        args.extend(_resolve_arg_token(token, spec_decl, context, config))

    environment = _resolve_environment(spec_decl.get("environment"), context)
    return ProviderLaunch(executable=executable, args=tuple(args), environment=environment)


def resolve_execution_model(packet_ctx: dict[str, Any], provider_cfg: dict[str, Any]) -> str | None:
    """Select the model already resolved by gateway dispatch.

    Gateway dispatch guarantees ``packet_ctx['model-id']`` after profile and
    alias resolution.  Adapters must not resolve aliases or independently
    prefer ``default-model``; the descriptor default is only a fallback for
    direct callers that do not use the gateway.
    """
    model = packet_ctx.get("model-id") or provider_cfg.get("default-model")
    return str(model) if model else None

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
    context_overrides: dict[str, Any] | None = None,
    include_prompt_body: bool = True,
) -> str:
    """Return the immutable prompt admitted by the gateway.

    Prompt definitions are now the sole public prompt authority.  The gateway
    materializes their complete text (including context and user body) before
    dispatch, so provider adapters must not consult a second prompt-template
    catalog or re-render mutable configuration here.
    """
    # Adapters may provide a normalized view (for example a provider-specific
    # prompt body or packet model) without changing the admitted packet.  The
    # override is an ephemeral projection only; it never reads configuration
    # or mutates the caller's mapping.
    effective_ctx = dict(packet_ctx)
    if context_overrides:
        effective_ctx.update(context_overrides)
    prompt_body = effective_ctx.get("prompt-body")
    if not isinstance(prompt_body, str) or not prompt_body.strip():
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        raise AudiaGenticError(
            code="VAL-APT-001",
            kind="agents",
            message="agent execution requires a non-empty prompt body",
            details={},
        )
    # This is provider-internal framing, not a configurable prompt authority.
    # The admitted prompt remains the only mutable/user-owned content.  Model
    # identity must come from the dispatch packet (the gateway's admitted
    # binding); provider_cfg is only the direct-call fallback.  Reading the
    # provider default here would reintroduce a second model authority and
    # made packet/model parity fail for free-instance dispatch.
    model = resolve_execution_model(effective_ctx, provider_cfg)
    framing = (
        f"Execution request for {title}. "
        f"request={effective_ctx.get('request-id')} "
        f"provider={effective_ctx.get('provider-id', provider_id)} "
        f"model={model}. "
        "Return a concise execution summary or the blocking reason if execution is impossible. "
    ).strip()
    if include_prompt_body:
        return f"{framing} Prompt body: {prompt_body.strip()}".strip()
    return framing


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
    prepare_launch: Callable[
        [dict[str, Any], dict[str, Any], list[str]], tuple[list[str], dict[str, str]]
    ]
    | None = None,
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
        if build_prompt is not None:
            prompt = build_prompt(packet_ctx, provider_cfg)
        else:
            prompt = default_build_prompt(
                packet_ctx,
                provider_cfg,
                provider_id=provider_id,
                title=title,
            )
        default_model = resolve_execution_model(packet_ctx, provider_cfg)
        working_root = packet_ctx.get("working-root")
        cwd = Path(working_root) if working_root else None

        execution_policy = provider_cfg.get("execution-policy", {})
        approval_mode = execution_policy.get("permission-mode", "auto")

        # One-shot execution is a launch kind: build the same normalized
        # ProviderLaunch every kind produces, then hand it to the pipe+parse
        # spawn strategy. Env is empty here — one-shot inherits os.environ via
        # launch_env_overlay rather than a spec-declared environment block.
        #
        # Stdin-fallback rule (MA35): if {prompt} is absent from the raw
        # args-template, the prompt reaches the process via stdin instead of
        # argv — no separate delivery flag needed. Compute the template once
        # here so both the context and input_text decisions are consistent.
        template = execution.get("args-template") or execution.get("args") or [
            "{approval-flags}",
            "{model-flags}",
            "{prompt}",
        ]
        prompt_in_argv = "{prompt}" in template

        spec = build_launch_spec(
            {"executable": exec_name, "aliases": list(aliases), **execution},
            context={
                "prompt": prompt if prompt_in_argv else None,
                "model": default_model,
                "approval-mode": approval_mode,
            },
        )
        command = [spec.executable, *spec.args]
        launch_environment: dict[str, str] | None = None
        if prepare_launch is not None:
            command, launch_environment = prepare_launch(packet_ctx, provider_cfg, command)

        stream_controls = packet_ctx.get("stream-controls", {})
        stdout_sinks, stderr_sinks = build_extractor_stream_sinks(
            extractor,
            packet_ctx=packet_ctx,
            stream_controls=stream_controls,
        )

        completed = run_streaming_command(
            command,
            cwd=cwd,
            input_text=None if prompt_in_argv else prompt,
            stdout_sinks=stdout_sinks,
            stderr_sinks=stderr_sinks,
            environment=launch_environment,
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
