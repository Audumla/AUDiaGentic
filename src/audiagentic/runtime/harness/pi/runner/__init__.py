from __future__ import annotations

import os
from pathlib import Path

from .command import _build_run_env, build_agent_command
from .constants import DEFAULT_PROVIDER, DEFAULT_RIG_PORT
from .context import (
    AgentContext,
    env_flag,
    env_with_pythonpath,
    load_harness_config,
    resolve_agent_bin,
)
from .models import load_model_profile
from .rig import cleanup_process_tree, cleanup_rig, launch_rig_if_needed
from .smoke import (
    check_endpoint,
    direct_mcp_smoke,
    query_server_model,
    query_server_version,
    run_agent,
)


def build_global_context(*, project_root: Path, agent_runtime: Path, enable_mcp: bool) -> AgentContext:
    harness_cfg = load_harness_config(project_root=project_root)
    requested_model = os.environ.get("AUDIAGENTIC_AG_MODEL") or harness_cfg.get("model")
    if not requested_model:
        raise SystemExit(
            "No model configured. Set AUDIAGENTIC_AG_MODEL environment variable "
            "or set 'model' in harness config."
        )
    profile_name, model_profile = load_model_profile(None, requested_model)
    rig_port = int(harness_cfg.get("rig", {}).get("port", DEFAULT_RIG_PORT))
    model_id = harness_cfg.get("model-id", "audiagentic-rig")
    endpoint, model, rig_pid, manages_rig = launch_rig_if_needed(
        requested_model, profile_name, model_profile, rig_port=rig_port, model_id=model_id
    )
    if not manages_rig:
        model = query_server_model(endpoint) or model
    rig_bin_dir = agent_runtime / "rig" / "bin"
    server_version = query_server_version(rig_bin_dir)
    provider = os.environ.get("AUDIAGENTIC_AG_PROVIDER", DEFAULT_PROVIDER)
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
    )
