from __future__ import annotations

import os
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.runtime.harness.config import (
    env_flag,
    load_harness_config,
    require_harness_provider,
    require_harness_rig_port,
)
from audiagentic.runtime.harness.context import (
    AgentContext,
    env_with_pythonpath,
    new_launch_runtime_root,
    resolve_agent_bin,
)
from audiagentic.runtime.harness.rig import launch_rig_if_needed
from audiagentic.runtime.rig.embedded.config import load_rig_model
from audiagentic.runtime.rig.models import (
    load_model_profile,
    query_server_model,
    query_server_version,
)

from .agent_run import (
    check_endpoint,
    direct_mcp_smoke,
    run_agent,
)
from .command import _build_run_env, build_agent_command

__all__ = [
    "AgentContext",
    "_build_run_env",
    "build_agent_command",
    "build_global_context",
    "check_endpoint",
    "direct_mcp_smoke",
    "env_flag",
    "env_with_pythonpath",
    "load_harness_config",
    "require_harness_provider",
    "require_harness_rig_port",
    "resolve_agent_bin",
    "run_agent",
    "translate_agent_args",
]


def translate_agent_args(params) -> list[str]:
    """Translate harness-agnostic RunnerParams to PI agent CLI flags.

    This is the harness-specific translation layer. If we swap to a
    different agent harness, only this function needs to change.
    """
    args: list[str] = []
    if params.prompt is not None:
        args.extend(["-p", params.prompt])
    if params.verbose:
        args.append("--verbose")
    if params.mode is not None:
        args.extend(["--mode", params.mode])
    return args


def build_global_context(*, project_root: Path, agent_runtime: Path, enable_mcp: bool) -> AgentContext:
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
        agent_home=agent_runtime,
        agent_dir=agent_runtime / "agent",
        agent_bin=resolve_agent_bin(agent_runtime),
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
