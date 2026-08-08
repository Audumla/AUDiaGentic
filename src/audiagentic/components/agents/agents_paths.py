"""Path resolution for the agents component."""

from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.paths.home import audiagentic_home
from audiagentic.foundation.paths.names import project_marker_path


def execution_profiles_path(project_root: Path) -> Path:
    """Return the path to the execution profiles YAML config file."""
    return project_marker_path(project_root) / "config" / "execution-profiles.yaml"


def roles_path(project_root: Path) -> Path:
    """Return the path to the roles YAML config file."""
    return project_marker_path(project_root) / "config" / "roles.yaml"


def agent_definitions_path(project_root: Path) -> Path:
    """Return the path to the agent definitions YAML config file."""
    return project_marker_path(project_root) / "config" / "agent-definitions.yaml"


_GATEWAY_ROOT = Path("runtime") / "agent-execution-gateway"


def gateway_root(project_root: Path) -> Path:
    """Return the .audiagentic/runtime/agent-execution-gateway root for a project."""
    return project_marker_path(project_root) / _GATEWAY_ROOT


# AS105/AS101: Compute Resource and Model Instance declarations describe
# shared infrastructure, not one project's intent -- they live at the
# user-global config tier (audiagentic_home()), never project-local. No
# project_root parameter, deliberately: a project must not be able to
# redefine the capacity of hardware it does not own (AS105's closed hazard).


def compute_resources_path() -> Path:
    """Return the path to the user-global compute resources YAML config file."""
    return audiagentic_home() / "config" / "compute-resources.yaml"


def model_instances_path() -> Path:
    """Return the path to the user-global model instances YAML config file."""
    return audiagentic_home() / "config" / "model-instances.yaml"


def gateway_request_dir(project_root: Path, request_id: str) -> Path:
    """Return the gateway request directory (.../agent-execution-gateway/<request-id>)."""
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


def gateway_sessions_root(project_root: Path) -> Path:
    """Return the .audiagentic/runtime/agent-execution-gateway/sessions root for a project."""
    return gateway_root(project_root) / "sessions"


def gateway_session_dir(project_root: Path, session_id: str) -> Path:
    """Return the gateway session directory (.../sessions/<session-id>)."""
    return gateway_sessions_root(project_root) / session_id


def gateway_session_path(project_root: Path, session_id: str) -> Path:
    """Return the record.json path for a gateway session."""
    return gateway_session_dir(project_root, session_id) / "record.json"


def gateway_session_timeline_path(project_root: Path, session_id: str) -> Path:
    """Return the timeline.ndjson path for a gateway session."""
    return gateway_session_dir(project_root, session_id) / "timeline.ndjson"


def gateway_session_binding_index_path(project_root: Path) -> Path:
    """Return the durable redacted provider-session binding index path."""
    return gateway_sessions_root(project_root) / "session-binding-index.json"


def gateway_session_binding_lock_path(project_root: Path) -> Path:
    """Return the project-local lock protecting the binding index."""
    return gateway_sessions_root(project_root) / "session-binding-index.lock"


# ── AS49: explicit resume idempotency ───────────────────────────────────────


def gateway_session_resume_idempotency_path(project_root: Path, session_id: str) -> Path:
    """Return the resume-idempotency record path for a source session.

    Scoped per source session-id (not global): a resume request is always
    "resume THIS terminal session," so co-locating the idempotency record
    beside the source session's own directory keeps one lock/file pair per
    resumable source rather than a single contested global index.
    """
    return gateway_session_dir(project_root, session_id) / "resume-idempotency.json"


def gateway_session_resume_lock_path(project_root: Path, session_id: str) -> Path:
    """Return the lock path guarding a source session's resume-idempotency record."""
    return gateway_session_dir(project_root, session_id) / "resume-idempotency.lock"


# ── AS31 Stage-2: output event paths ───────────────────────────────────────

_OUTPUT_DIR = Path("output")
_OUTPUT_EVENTS_DIR = _OUTPUT_DIR / "events"


def gateway_output_dir(project_root: Path, request_id: str) -> Path:
    """Return the output directory for a gateway request
    (.../agent-execution-gateway/<request-id>/output)."""
    return gateway_request_dir(project_root, request_id) / _OUTPUT_DIR


def gateway_output_events_dir(project_root: Path, request_id: str) -> Path:
    """Return the output events subdirectory for a gateway request
    (.../agent-execution-gateway/<request-id>/output/events)."""
    return gateway_output_dir(project_root, request_id) / _OUTPUT_EVENTS_DIR


def gateway_output_event_path(project_root: Path, request_id: str, sequence: int) -> Path:
    """Return the per-event JSON path for a given sequence number.
    (.../agent-execution-gateway/<request-id>/output/events/<seq>.json)."""
    return gateway_output_events_dir(project_root, request_id) / f"{sequence}.json"


def gateway_output_index_path(project_root: Path, request_id: str) -> Path:
    """Return the output index path for a gateway request.
    (.../agent-execution-gateway/<request-id>/output/index.json)."""
    return gateway_output_dir(project_root, request_id) / "index.json"


def gateway_output_lock_path(project_root: Path, request_id: str) -> Path:
    """Return the per-request lock protecting output append operations."""
    return gateway_request_dir(project_root, request_id) / "output.lock"
