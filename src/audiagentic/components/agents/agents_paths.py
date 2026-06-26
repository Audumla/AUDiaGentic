"""Path resolution for the agents component."""
from __future__ import annotations

from pathlib import Path


def agent_profiles_path(project_root: Path) -> Path:
    """Return the path to the agent profiles YAML config file."""
    return project_root / ".audiagentic" / "config" / "agent-profiles.yaml"
