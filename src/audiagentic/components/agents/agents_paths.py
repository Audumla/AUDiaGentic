"""Path resolution for the agents component."""

from __future__ import annotations

import os
from pathlib import Path

from audiagentic.foundation.paths.names import project_marker_path


def agent_profiles_path(project_root: Path) -> Path:
    """Return the path to the agent profiles YAML config file."""
    return project_marker_path(project_root) / "config" / "agent-profiles.yaml"


_GATEWAY_ROOT = Path("runtime") / "agent-execution-gateway"
_LEGACY_GATEWAY_ROOT = (
    Path("runtime") / "agent-llm-gateway"
)  # SH12 legacy — delete after one release cycle
_migrated_gateway_roots: set[Path] = set()


def gateway_root(project_root: Path) -> Path:
    """Return the .audiagentic/runtime/agent-execution-gateway root for a project.

    Performs a one-shot atomic rename from the legacy agent-llm-gateway root
    on first access (SH12 migration). Idempotent and concurrent-safe via StartupLock.
    """
    marker = project_marker_path(project_root)
    if project_root in _migrated_gateway_roots:
        return marker / _GATEWAY_ROOT

    new_root = marker / _GATEWAY_ROOT
    old_root = marker / _LEGACY_GATEWAY_ROOT

    if not old_root.is_dir():
        return new_root

    # Both roots exist — warn and use new (same as sessions precedent)
    if new_root.exists():
        import logging

        logging.getLogger(__name__).warning(
            "both legacy and current gateway roots exist; using current, leaving legacy in place",
            extra={"legacy-root": str(old_root), "current-root": str(new_root)},
        )
        _migrated_gateway_roots.add(project_root)
        return new_root

    try:
        new_root.parent.mkdir(parents=True, exist_ok=True)
        from audiagentic.foundation.system.process import StartupLock

        with StartupLock(marker / "gateway-rename.lock"):
            if not old_root.is_dir():
                return new_root
            if new_root.exists():  # re-check under lock
                _migrated_gateway_roots.add(project_root)
                return new_root
            os.replace(str(old_root), str(new_root))  # atomic same-volume dir rename
        _migrated_gateway_roots.add(project_root)
    except OSError:
        import logging

        logging.getLogger(__name__).warning(
            "failed to migrate legacy gateway root; falling back to legacy path",
            extra={"legacy-root": str(old_root)},
            exc_info=True,
        )
        return old_root

    return new_root


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


# Legacy defect (SH review C3): session paths were rooted at the bare project
# root instead of the .audiagentic marker, creating <project>/runtime/... .
_LEGACY_SESSIONS_ROOT = Path("runtime") / "agent-llm-gateway" / "sessions"
_migrated_session_roots: set[Path] = set()


def _migrate_legacy_sessions_root(project_root: Path, target: Path) -> None:
    """One-time move of the accidental top-level sessions tree into the marker.

    Both-roots-present is surfaced, never silently merged: the legacy tree is
    left in place and a warning names it so an operator can reconcile.
    """
    if project_root in _migrated_session_roots:
        return
    _migrated_session_roots.add(project_root)
    legacy = project_root / _LEGACY_SESSIONS_ROOT
    try:
        if not legacy.is_dir():
            return
        if target.exists():
            import logging

            logging.getLogger(__name__).warning(
                "both legacy and current gateway session roots exist; leaving legacy in place",
                extra={"legacy-root": str(legacy), "current-root": str(target)},
            )
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(target)
        # Remove the now-empty accidental top-level runtime tree if nothing
        # else was created under it.
        for parent in (legacy.parent, legacy.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break
    except OSError:
        import logging

        logging.getLogger(__name__).warning(
            "failed to migrate legacy gateway session root",
            extra={"legacy-root": str(legacy)},
            exc_info=True,
        )


def gateway_sessions_root(project_root: Path) -> Path:
    """Return the .audiagentic/runtime/agent-execution-gateway/sessions root for a project."""
    target = gateway_root(project_root) / "sessions"
    _migrate_legacy_sessions_root(project_root, target)
    return target


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
