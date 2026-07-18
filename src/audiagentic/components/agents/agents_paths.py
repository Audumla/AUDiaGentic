"""Path resolution for the agents component."""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.paths.names import project_marker_path


def agent_profiles_path(project_root: Path) -> Path:
    """Return the path to the agent profiles YAML config file."""
    return project_marker_path(project_root) / "config" / "agent-profiles.yaml"


_GATEWAY_ROOT = Path("runtime") / "agent-llm-gateway"


def gateway_root(project_root: Path) -> Path:
    """Return the .audiagentic/runtime/agent-llm-gateway root for a project."""
    return project_marker_path(project_root) / _GATEWAY_ROOT


def gateway_request_dir(project_root: Path, request_id: str) -> Path:
    """Return the gateway request directory (.../agent-llm-gateway/<request-id>)."""
    return gateway_root(project_root) / request_id


def gateway_request_path(project_root: Path, request_id: str) -> Path:
    """Return the record.json path for a gateway request."""
    return gateway_request_dir(project_root, request_id) / "record.json"


def gateway_timeline_path(project_root: Path, request_id: str) -> Path:
    """Return the timeline.ndjson path for a gateway request."""
    return gateway_request_dir(project_root, request_id) / "timeline.ndjson"


def gateway_admission_lock_path(project_root: Path) -> Path:
    """Return the project-local lock protecting idempotent admission."""
    return gateway_root(project_root) / "admission.lock"


def gateway_idempotency_index_path(project_root: Path, key_digest: str) -> Path:
    """Return the opaque, hashed idempotency-index entry for one request key."""
    return gateway_root(project_root) / "idempotency" / f"{key_digest}.json"


_SESSIONS_ROOT = _GATEWAY_ROOT / "sessions"


def gateway_sessions_root(project_root: Path) -> Path:
    """Return the .../agent-llm-gateway/sessions root for a project."""
    return project_root / _SESSIONS_ROOT


def gateway_session_dir(project_root: Path, session_id: str) -> Path:
    """Return the gateway session directory (.../sessions/<session-id>)."""
    return gateway_sessions_root(project_root) / session_id


def gateway_session_path(project_root: Path, session_id: str) -> Path:
    """Return the record.json path for a gateway session."""
    return gateway_session_dir(project_root, session_id) / "record.json"


def gateway_session_timeline_path(project_root: Path, session_id: str) -> Path:
    """Return the timeline.ndjson path for a gateway session."""
    return gateway_session_dir(project_root, session_id) / "timeline.ndjson"
