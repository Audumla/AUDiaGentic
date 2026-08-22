"""Path resolution for the agents component."""

from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.paths.home import audiagentic_home
from audiagentic.foundation.paths.names import project_marker_path


def agents_config_path(project_root: Path) -> Path:
    """Return the canonical project-owned Agents configuration document."""
    return project_marker_path(project_root) / "config" / "agents.yaml"


def global_agents_config_path() -> Path:
    """Return the machine-global canonical Agents configuration document."""
    return audiagentic_home() / "config" / "agents.yaml"


def agents_runtime_root(project_root: Path) -> Path:
    return project_marker_path(project_root) / "runtime" / "agents"


def agent_context_root(project_root: Path) -> Path:
    return agents_runtime_root(project_root) / "contexts"


def agent_context_path(project_root: Path, context_id: str) -> Path:
    return agent_context_root(project_root) / context_id / "record.json"


def agent_context_lock_path(project_root: Path, context_id: str) -> Path:
    return agent_context_root(project_root) / context_id / "mutation.lock"


def agent_work_root(project_root: Path) -> Path:
    return agents_runtime_root(project_root) / "work"


def agent_work_path(project_root: Path, work_id: str) -> Path:
    return agent_work_root(project_root) / work_id / "record.json"


def agent_work_lock_path(project_root: Path, work_id: str) -> Path:
    return agent_work_root(project_root) / work_id / "mutation.lock"


def agent_work_inputs_path(project_root: Path, work_id: str) -> Path:
    return agent_work_root(project_root) / work_id / "inputs.ndjson"


def execution_profiles_path(project_root: Path) -> Path:
    """Return the legacy profile path used only by one-time migration."""
    return project_marker_path(project_root) / "config" / "execution-profiles.yaml"


def roles_path(project_root: Path) -> Path:
    """Return the legacy roles path used only by one-time migration."""
    return project_marker_path(project_root) / "config" / "roles.yaml"


def agent_definitions_path(project_root: Path) -> Path:
    """Return the legacy definitions path used only by one-time migration."""
    return project_marker_path(project_root) / "config" / "agent-definitions.yaml"


_GATEWAY_ROOT = Path("runtime") / "agent-execution-gateway"


def gateway_root(project_root: Path) -> Path:
    """Return the .audiagentic/runtime/agent-execution-gateway root for a project."""
    return project_marker_path(project_root) / _GATEWAY_ROOT


def gateway_request_dir(project_root: Path, request_id: str) -> Path:
    """Return the gateway request directory (.../agent-execution-gateway/<request-id>)."""
    return gateway_root(project_root) / request_id


def gateway_request_path(project_root: Path, request_id: str) -> Path:
    """Return the record.json path for a gateway request."""
    return gateway_request_dir(project_root, request_id) / "record.json"


def gateway_final_response_path(project_root: Path, request_id: str) -> Path:
    """Return the gateway-owned immutable terminal response artifact path."""
    return gateway_request_dir(project_root, request_id) / "output" / "final-response.txt"


def gateway_publication_path(project_root: Path, request_id: str, *, attempt_epoch: int = 1) -> Path:
    """Return the durable broker-publication intent for one request attempt."""
    return gateway_request_dir(project_root, request_id) / f"publication-{attempt_epoch}.json"


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


def gateway_session_root_registry_path(project_root: Path) -> Path:
    """Return the durable session-root/request lineage registry path."""
    return gateway_sessions_root(project_root) / "session-root-registry.json"


def gateway_session_root_registry_lock_path(project_root: Path) -> Path:
    """Return the lock guarding the durable session-root registry."""
    return gateway_sessions_root(project_root) / "session-root-registry.lock"


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


def gateway_session_control_idempotency_path(project_root: Path, session_id: str) -> Path:
    """Return the durable generic-control idempotency record for a session."""
    return gateway_session_dir(project_root, session_id) / "control-idempotency.json"


def gateway_session_control_lock_path(project_root: Path, session_id: str) -> Path:
    """Return the lock guarding a session's generic-control idempotency record."""
    return gateway_session_dir(project_root, session_id) / "control-idempotency.lock"


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


def gateway_retention_lock_path(project_root: Path) -> Path:
    """Return the cross-surface lock for retention pins and purge deletion."""
    return gateway_root(project_root) / "retention.mutation.lock"


def gateway_provenance_log_path(project_root: Path) -> Path:
    """Return the GP27 request-record provenance log path.

    Co-located with the request directories it traces
    (.../agent-execution-gateway/provenance.ndjson). Best-effort, bounded:
    instrumentation must never change request lifecycle behavior.
    """
    return gateway_root(project_root) / "provenance.ndjson"
