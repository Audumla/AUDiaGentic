"""Pi harness runner context — pi-specific context type and helpers.

Generic config helpers (load_harness_config, require_harness_provider, etc.)
live in audiagentic.runtime.harness.config and are re-exported here for
backwards compatibility with existing pi-internal callers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from audiagentic.runtime.harness.config import (
    env_flag,
    load_harness_config,
    require_harness_provider,
    require_harness_rig_port,
    require_smoke_timeout,
)

__all__ = [
    "AgentContext",
    "env_flag",
    "env_with_pythonpath",
    "load_harness_config",
    "require_harness_provider",
    "require_harness_rig_port",
    "require_smoke_timeout",
    "resolve_agent_bin",
]


@dataclass
class AgentContext:
    project_root: Path
    agent_runtime: Path
    agent_home: Path
    agent_dir: Path
    agent_bin: Path
    agent_work: Path
    agent_log_dir: Path
    endpoint: str
    model: str
    model_profile: dict[str, object]
    profile_name: str
    provider: str
    rig_pid: int | None
    manages_rig: bool
    enable_mcp: bool
    server_version: str | None = None
    harness_cfg: dict = field(default_factory=dict)


def env_with_pythonpath() -> dict[str, str]:
    return os.environ.copy()


def resolve_agent_bin(agent_runtime: Path) -> Path:
    return agent_runtime / "cli" / "node_modules" / ".bin" / (
        "pi.cmd" if os.name == "nt" else "pi"
    )
