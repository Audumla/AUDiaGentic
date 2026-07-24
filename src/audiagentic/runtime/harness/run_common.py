from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from audiagentic.foundation.cli_io import print_message
from audiagentic.foundation.contracts.errors import make_error
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
            details={"harness_type": harness_type, "hint": f"install {harness_type}, then run: audiagentic bootstrap"},
        )

    harness_cfg = load_harness_config(project_root=project_root)
    requested_model = os.environ.get("AUDIAGENTIC_AG_MODEL") or harness_cfg.get("rig", {}).get("model")
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
    endpoint, model, rig_pid, manages_rig = launch_rig_if_needed(
        requested_model, profile_name, model_profile, rig_port=rig_port, model_id=model_id
    )
    if not manages_rig:
        model = query_server_model(endpoint) or model

    rig_bin_dir = agent_runtime / "rig" / "bin"
    server_version = query_server_version(rig_bin_dir)
    provider = os.environ.get("AUDIAGENTIC_AG_PROVIDER") or require_harness_provider(harness_cfg)
    resolved_enable_mcp = enable_mcp or bool(harness_cfg.get("mcp", {}).get("enabled", False))

    return AgentContext(
        project_root=project_root,
        agent_runtime=agent_runtime,
        agent_work=project_root,
        agent_log_dir=project_root / ".audiagentic" / "logs" / "cli",
        endpoint=endpoint,
        model=model,
        model_profile=model_profile,
        profile_name=profile_name,
        provider=provider,
        rig_pid=rig_pid,
        manages_rig=manages_rig,
        enable_mcp=resolved_enable_mcp,
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
    env["AUDIAGENTIC_RIG_TYPE"] = "embedded" if ctx.manages_rig else "external"
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
        handle.write(json.dumps({"event": "agent_run_finished", "returncode": int(returncode)}) + "\n")


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
