from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.system.supervised_process import spawn_supervised
from audiagentic.runtime.harness.context import AgentContext, new_launch_runtime_root


def build_global_context(
    harness_type: str,
    *,
    project_root: Path,
    agent_runtime: Path,
    enable_mcp: bool,
) -> AgentContext:
    """Harness-agnostic global context: config, model/rig resolution, provider.

    Was previously duplicated near-identically between the pi and opencode
    runners (HA03). Fully harness-blind -- binary resolution and any other
    harness-specific launch state lives in each provider's
    components/providers/adapters/<harness>/interactive.py builder instead.
    """
    from audiagentic.runtime.harness.config import (
        load_harness_config,
        require_harness_provider,
        require_harness_rig_port,
    )
    from audiagentic.runtime.harness.resolution import harness_cli_available
    from audiagentic.runtime.harness.rig import launch_rig_if_needed
    from audiagentic.runtime.rig.embedded.config import load_rig_model
    from audiagentic.runtime.rig.models import (
        load_model_profile,
        query_server_model,
        query_server_version,
    )

    if harness_cli_available(harness_type) is None:
        raise make_error(
            prefix="RES",
            component="HRNRUN",
            number=1,
            kind="harness",
            message=f"No system-installed {harness_type} harness found on PATH.",
            details={
                "harness_type": harness_type,
                "hint": f"install {harness_type}, then run: audiagentic bootstrap",
            },
        )

    harness_cfg = load_harness_config(project_root=project_root)
    requested_model = os.environ.get("AUDIAGENTIC_AG_MODEL") or harness_cfg.get("rig", {}).get(
        "model"
    )
    if not requested_model:
        raise make_error(
            prefix="CFG",
            component="HCFG",
            number=9,
            kind="harness-config",
            message=(
                "No model configured. Set AUDIAGENTIC_AG_MODEL environment variable "
                "or set 'model' in harness config."
            ),
            details={"field": "rig.model"},
        )

    profile_name, model_profile = load_model_profile(None, requested_model)
    rig_port = require_harness_rig_port(harness_cfg)
    _, model_id = load_rig_model()
    rig_connection = launch_rig_if_needed(
        requested_model, profile_name, model_profile, rig_port=rig_port, model_id=model_id
    )
    if not rig_connection.embedded:
        model = query_server_model(rig_connection.endpoint) or rig_connection.model

    rig_bin_dir = agent_runtime / "rig" / "bin"
    server_version = query_server_version(rig_bin_dir)
    provider = os.environ.get("AUDIAGENTIC_AG_PROVIDER") or require_harness_provider(harness_cfg)
    resolved_enable_mcp = enable_mcp or bool(harness_cfg.get("mcp", {}).get("enabled", False))

    return AgentContext(
        project_root=project_root,
        agent_runtime=agent_runtime,
        agent_work=project_root,
        agent_log_dir=project_root / ".audiagentic" / "logs" / "cli",
        endpoint=rig_connection.endpoint,
        model=rig_connection.model if rig_connection.embedded else model,
        model_profile=model_profile,
        profile_name=profile_name,
        provider=provider,
        embedded_rig=rig_connection.embedded,
        enable_mcp=resolved_enable_mcp,
        rig_attachment=rig_connection.attachment,
        server_version=server_version,
        harness_cfg=harness_cfg,
        launch_runtime_root=new_launch_runtime_root(agent_runtime),
    )


def build_base_run_env(ctx: AgentContext) -> dict[str, str]:
    import os

    env = os.environ.copy()
    env["AUDIAGENTIC_REPO_ROOT"] = str(ctx.project_root)
    env["AUDIAGENTIC_AG_BASE_URL"] = ctx.endpoint
    env["AUDIAGENTIC_AG_MODEL"] = ctx.model
    env["AUDIAGENTIC_RIG_TYPE"] = "embedded" if ctx.embedded_rig else "external"
    env["AUDIAGENTIC_RIG_PROFILE"] = ctx.profile_name
    env["OPENAI_API_BASE"] = ctx.endpoint
    env["OPENAI_BASE_URL"] = ctx.endpoint
    env["OPENAI_API_KEY"] = "dummy"
    return env


def make_log_path(ctx: AgentContext, mode: str) -> Path:
    ctx.agent_log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ctx.agent_log_dir / f"{mode}-{stamp}.log"


def write_run_started(log_path: Path, ctx: AgentContext, agent_args: list[str]) -> None:
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "event": "agent_run_started",
                    "project_root": str(ctx.project_root),
                    "provider": ctx.provider,
                    "model": ctx.model,
                    "endpoint": ctx.endpoint,
                    "mcp": ctx.enable_mcp,
                    "args": agent_args,
                },
                indent=2,
            )
            + "\n"
        )


def append_run_finished(log_path: Path, returncode: int) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps({"event": "agent_run_finished", "returncode": int(returncode)}) + "\n"
        )


def print_startup_info(
    ctx: AgentContext,
    log_path: Path,
    *,
    title: str,
    extra_lines: list[str] | None = None,
) -> None:
    ui_cfg = ctx.harness_cfg.get("ui", {})
    banner = ui_cfg.get("startup_banner")
    if banner:
        print_message(banner, flush=str(banner).endswith("\n"))
    if not ui_cfg.get("show_startup_info", True):
        return
    print_message(title)
    print_message(f"  Project:  {ctx.project_root}")
    print_message(f"  Provider: {ctx.provider}")
    print_message(f"  Model:    {ctx.model}")
    print_message(f"  Endpoint: {ctx.endpoint}")
    if ctx.server_version:
        print_message(f"  Server:   {ctx.server_version}")
    print_message(f"  MCP:      {'enabled' if ctx.enable_mcp else 'disabled'}")
    for line in extra_lines or []:
        print_message(line)
    print_message(f"  Log:      {log_path}")
    print_message("")


def run_supervised(command: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> int:
    from audiagentic.foundation.system.supervised_process import supervised_run

    returncode = int(supervised_run(command, cwd=cwd, env=env))
    append_run_finished(log_path, returncode)
    return returncode


def run_provider_agent(
    ctx: AgentContext,
    provider_id: str,
    runner_params: object,
    *,
    smoke: bool,
) -> int:
    """Run an interactive provider through the public providers API.

    Runtime owns the shared session lifecycle, MCP projection, logging and
    supervision.  The provider adapter owns command shape and environment.
    No runtime package is required for an individual provider.
    """
    from audiagentic.components.providers import providers_api
    from audiagentic.runtime.harness.config import require_smoke_timeout
    from audiagentic.runtime.rig.http import require_models_endpoint

    if not smoke:
        print_message("\033[2J\033[H", flush=False)

    ctx.agent_work.mkdir(parents=True, exist_ok=True)
    (ctx.project_root / ".audiagentic" / "sessions").mkdir(parents=True, exist_ok=True)
    if ctx.enable_mcp:
        if ctx.prepared_mcp_surface is None:
            ctx.prepared_mcp_surface = providers_api.prepare_projected_provider_mcp_surface(
                ctx.project_root,
                provider_id=provider_id,
                runtime_root=ctx.launch_runtime_root,
                require_exact_isolation=True,
            )
        mcp_surface = ctx.prepared_mcp_surface
    else:
        mcp_surface = None

    launch = providers_api.prepare_interactive_provider_launch(
        ctx.project_root,
        provider_id=provider_id,
        provider=ctx.provider,
        model=ctx.model,
        agent_runtime=ctx.agent_runtime,
        mcp_surface=mcp_surface,
        # Raw list[str] is the legacy passthrough form (see runner_args below)
        # — it is appended to the command after launch, never translated by
        # a provider adapter's translate_runner_args(), which expects an
        # actual RunnerParams object with .prompt/.verbose/.mode attributes.
        runner_params=None if isinstance(runner_params, list) else runner_params,
        smoke=smoke,
    )
    env = {**build_base_run_env(ctx), **launch.environment}
    log_path = make_log_path(ctx, "smoke" if smoke else "run")
    command = [launch.executable, *launch.args]

    if smoke:
        print_message(f"Checking local LLM endpoint: {ctx.endpoint}/models")
        require_models_endpoint(ctx.endpoint, timeout=15)
        timeout = float(
            os.environ.get("AUDIAGENTIC_AG_SMOKE_TIMEOUT") or require_smoke_timeout(ctx.harness_cfg)
        )
        with log_path.open("w", encoding="utf-8") as handle:
            supervised = spawn_supervised(
                command, cwd=ctx.agent_work, env=env, stdout=handle, stderr=subprocess.STDOUT
            )
            try:
                returncode = supervised.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                supervised.close()
                handle.write(f"\nSmoke timed out after {timeout:.1f}s\n")
                return 124
        sys.stdout.write(log_path.read_text(encoding="utf-8"))
        return int(returncode)

    print_startup_info(ctx, log_path, title=f"AUDiaGentic ({provider_id})")
    runner_args = (
        list(runner_params)
        if isinstance(runner_params, list)
        else providers_api.translate_interactive_runner_args(provider_id, runner_params)
    )
    write_run_started(log_path, ctx, runner_args)
    # Provider launch builders already incorporate RunnerParams.  Raw list
    # arguments are the legacy passthrough form and are appended here.
    return run_supervised(
        [*command, *runner_args] if isinstance(runner_params, list) else command,
        ctx.agent_work,
        env,
        log_path,
    )
