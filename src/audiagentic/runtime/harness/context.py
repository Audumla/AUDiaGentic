"""Canonical harness runner context.

Single AgentContext dataclass shared by all harness runners. Harness-specific
launch mechanics (which binary, which flags, which extra env vars) live under
components/providers/adapters/<harness>/interactive.py, not here -- this
context only carries the harness-agnostic session/environment state every
launch needs (HA03).
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from audiagentic.runtime.harness.config import require_smoke_timeout  # noqa: F401 -- re-exported

__all__ = [
    "AgentContext",
    "env_with_pythonpath",
    "new_launch_runtime_root",
    "require_smoke_timeout",
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
    agent_runtime: Path | None = None
    launch_runtime_root: Path | None = None
    prepared_mcp_surface: object | None = None


def env_with_pythonpath() -> dict[str, str]:
    return os.environ.copy()


def new_launch_runtime_root(agent_runtime: Path) -> Path:
    """Return a unique request-owned root without mutating shared config."""
    return agent_runtime / "launches" / uuid.uuid4().hex
