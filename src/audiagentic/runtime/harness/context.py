"""Canonical harness runner context.

Single AgentContext dataclass shared by both pi and opencode harness runners.
Pi-specific fields (agent_runtime, agent_home, agent_dir, agent_bin) default
to None; the pi runner always sets them at construction.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.runtime.harness.config import require_smoke_timeout  # noqa: F401 -- re-exported

__all__ = [
    "AgentContext",
    "env_with_pythonpath",
    "new_launch_runtime_root",
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
    launch_runtime_root: Path | None = None
    prepared_mcp_surface: object | None = None


def env_with_pythonpath() -> dict[str, str]:
    return os.environ.copy()


def new_launch_runtime_root(agent_runtime: Path) -> Path:
    """Return a unique request-owned root without mutating shared config."""
    return agent_runtime / "launches" / uuid.uuid4().hex


def resolve_agent_bin(agent_runtime: Path) -> Path:
    # The harness is whatever is installed on the system — AUDiaGentic no longer
    # bundles a copy. ``agent_runtime`` is retained for signature compatibility
    # (it still hosts the rig backend + materialized config), but the CLI comes
    # from PATH.
    from audiagentic.runtime.harness.resolution import harness_cli_available

    system = harness_cli_available("pi")
    if system is None:
        raise make_error(
            prefix="RES",
            component="PIRUN",
            number=3,
            kind="pi-harness",
            message="No system-installed pi harness found on PATH.",
            details={"hint": "install pi, or set harness.type/order in harness/ag config"},
        )
    return Path(system)
