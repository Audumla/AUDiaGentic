"""Opencode harness runner.

Uses the same embedded rig as the pi harness — same model profiles, same
endpoint resolution, same shutdown management. Differs only in the agent
CLI invocation (opencode CLI vs pi TUI).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from audiagentic.cli_io import print_message
from audiagentic.foundation.contracts.errors import make_error
from audiagentic.runtime.harness.context import AgentContext
from audiagentic.runtime.harness.run_common import (
    build_base_run_env,
    make_log_path,
    print_startup_info,
    run_supervised,
    write_run_started,
)

logger = logging.getLogger(__name__)


def env_flag(name: str, default: bool = False) -> bool:
    truthy = {"1", "true", "yes", "on"}
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in truthy


def build_global_context(
    *,
    project_root: Path,
    agent_runtime: Path,
    enable_mcp: bool,
) -> AgentContext:
    from audiagentic.runtime.harness.config import (
        load_harness_config,
        require_harness_provider,
        require_harness_rig_port,
    )
    from audiagentic.runtime.harness.rig import launch_rig_if_needed
    from audiagentic.runtime.rig.embedded.config import load_rig_model
    from audiagentic.runtime.rig.models import (
        load_model_profile,
        query_server_model,
        query_server_version,
    )

    if shutil.which("opencode") is None:
        raise make_error(
            prefix="CFG",
            component="OCINST",
            number=2,
            kind="opencode-harness",
            message=(
                "opencode CLI not found on PATH. "
                "Install it with: audiagentic install  or  npm install -g opencode-ai"
            ),
        )

    harness_cfg = load_harness_config(project_root=project_root)
    requested_model = (
        os.environ.get("AUDIAGENTIC_AG_MODEL")
        or harness_cfg.get("rig", {}).get("model")
    )
    if not requested_model:
        raise make_error(
            prefix="CFG",
            component="HCFG",
            number=11,
            kind="harness-config",
            message="No model configured. Set AUDIAGENTIC_AG_MODEL or rig.model in ag.yaml.",
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
    server_version = query_server_version(rig_bin_dir) if rig_bin_dir.exists() else None

    provider = (
        os.environ.get("AUDIAGENTIC_AG_PROVIDER")
        or require_harness_provider(harness_cfg)
    )
    resolved_enable_mcp = enable_mcp or bool(harness_cfg.get("mcp", {}).get("enabled", False))

    return AgentContext(
        project_root=project_root,
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
    )


def translate_agent_args(params) -> list[str]:
    """Translate RunnerParams to opencode CLI flags."""
    args: list[str] = []
    if params.mode == "json":
        args.extend(["--output-format", "json"])
    if params.prompt is not None:
        args.extend(["--message", params.prompt])
    return args


def _build_run_env(ctx: AgentContext) -> dict[str, str]:
    return build_base_run_env(ctx)


def run_agent(ctx: AgentContext, agent_args: list[str], *, smoke: bool) -> int:
    from audiagentic.runtime.rig.http import require_models_endpoint

    executable = shutil.which("opencode")
    if executable is None:
        raise make_error(
            prefix="CFG",
            component="OCINST",
            number=3,
            kind="opencode-harness",
            message="opencode CLI not found on PATH",
        )

    env = _build_run_env(ctx)
    mode = "smoke" if smoke else "run"
    log_path = make_log_path(ctx, mode)

    if smoke:
        print_message(f"Checking local LLM endpoint: {ctx.endpoint}/models")
        require_models_endpoint(ctx.endpoint, timeout=15)
        print_message(f"Checking opencode CLI: {executable}")
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise make_error(
                prefix="EXT",
                component="OCINST",
                number=4,
                kind="opencode-harness",
                message=f"opencode --version failed: {result.stderr.strip()}",
                details={"returncode": result.returncode},
            )
        version = (result.stdout + result.stderr).strip().split("\n")[0]
        print_message(f"opencode: {version}")
        log_path.write_text(f"smoke ok\nopencode: {version}\n", encoding="utf-8")
        return 0

    print_startup_info(ctx, log_path, title="AUDiaGentic (opencode)")

    cmd = [executable] + agent_args

    # Rig shutdown is owned exclusively by the refcounted client registry
    # (shutdown_rig_if_last in commands/launch.py). Killing rig_pid here would
    # destroy a rig other harnesses may still be attached to — rig_pid marks
    # the starter, not the last user (PR04).
    write_run_started(log_path, ctx, agent_args)
    return run_supervised(cmd, ctx.agent_work, env, log_path)
