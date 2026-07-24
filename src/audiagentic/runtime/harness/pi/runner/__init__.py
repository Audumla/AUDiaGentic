from __future__ import annotations

from pathlib import Path

from audiagentic.runtime.harness.config import (
    env_flag,
    load_harness_config,
    require_harness_provider,
    require_harness_rig_port,
)
from audiagentic.runtime.harness.context import AgentContext, env_with_pythonpath
from audiagentic.runtime.harness.run_common import build_global_context as _build_global_context

from .agent_run import (
    check_endpoint,
    direct_mcp_smoke,
    run_agent,
)

__all__ = [
    "AgentContext",
    "build_global_context",
    "check_endpoint",
    "direct_mcp_smoke",
    "env_flag",
    "env_with_pythonpath",
    "load_harness_config",
    "require_harness_provider",
    "require_harness_rig_port",
    "run_agent",
    "translate_agent_args",
]


def translate_agent_args(params) -> list[str]:
    """Translate harness-agnostic RunnerParams to pi CLI flags.

    Delegates to the provider-owned translation
    (components/providers/adapters/pi/interactive.py) — runtime only
    forwards the call (HA03).
    """
    from audiagentic.components.providers.adapters.pi.interactive import translate_runner_args

    return translate_runner_args(params)


def build_global_context(*, project_root: Path, agent_runtime: Path, enable_mcp: bool) -> AgentContext:
    return _build_global_context(
        "pi", project_root=project_root, agent_runtime=agent_runtime, enable_mcp=enable_mcp
    )
