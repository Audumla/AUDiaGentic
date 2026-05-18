from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


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


def load_harness_config(project_root: Path | None = None) -> dict:
    from audiagentic.provisioning.config_loader import load_layered_config
    from .constants import _HARNESS_CONFIG
    return load_layered_config(
        pkg_default_path=_HARNESS_CONFIG,
        project_root=project_root,
        namespace="harness/ag",
    )


def env_with_pythonpath() -> dict[str, str]:
    return os.environ.copy()


def resolve_agent_bin(agent_runtime: Path) -> Path:
    import os
    return agent_runtime / "cli" / "node_modules" / ".bin" / ("pi.cmd" if os.name == "nt" else "pi")


def env_flag(name: str, default: bool = False) -> bool:
    from .constants import TRUTHY
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in TRUTHY
