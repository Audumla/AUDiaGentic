"""Path resolution for the agents component."""
from __future__ import annotations

from pathlib import Path


def agent_profiles_path(project_root: Path) -> Path:
    """Return the path to the agent profiles YAML config file."""
    return project_root / ".audiagentic" / "config" / "agent-profiles.yaml"


_GATEWAY_ROOT = Path(".audiagentic") / "runtime" / "agent-llm-gateway"


def gateway_root(project_root: Path) -> Path:
    """Return the .audiagentic/runtime/agent-llm-gateway root for a project."""
    return project_root / _GATEWAY_ROOT


def gateway_request_dir(project_root: Path, request_id: str) -> Path:
    """Return the gateway request directory (.../agent-llm-gateway/<request-id>)."""
    return gateway_root(project_root) / request_id


def gateway_request_path(project_root: Path, request_id: str) -> Path:
    """Return the record.json path for a gateway request."""
    return gateway_request_dir(project_root, request_id) / "record.json"


def gateway_timeline_path(project_root: Path, request_id: str) -> Path:
    """Return the timeline.ndjson path for a gateway request."""
    return gateway_request_dir(project_root, request_id) / "timeline.ndjson"
