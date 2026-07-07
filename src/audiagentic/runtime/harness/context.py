"""Canonical harness runner context.

Single AgentContext dataclass shared by both pi and opencode harness runners.
Pi-specific fields (agent_runtime, agent_home, agent_dir, agent_bin) default
to None; the pi runner always sets them at construction.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from audiagentic.runtime.harness.config import require_smoke_timeout  # noqa: F401 -- re-exported

__all__ = [
    "AgentContext",
    "env_with_pythonpath",
    "require_smoke_timeout",
    "resolve_agent_bin",
]


@dataclass
class AgentContext:
    project_root: Path
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
    # pi-specific fields (always set by pi runner, optional for opencode)
    agent_runtime: Path | None = None
    agent_home: Path | None = None
    agent_dir: Path | None = None
    agent_bin: Path | None = None


def env_with_pythonpath() -> dict[str, str]:
    return os.environ.copy()


def resolve_agent_bin(agent_runtime: Path) -> Path:
    return agent_runtime / "cli" / "node_modules" / ".bin" / (
        "pi.cmd" if os.name == "nt" else "pi"
    )
