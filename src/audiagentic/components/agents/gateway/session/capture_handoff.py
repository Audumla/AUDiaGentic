"""Private, request-owned authority for observation-only capture handoff."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.time import now_iso_z

OWNER_KEYS = ("dispatch-owner-epoch", "worker-id", "attempt-epoch")


def capture_owner(record: dict[str, Any]) -> dict[str, Any] | None:
    """Freeze the dispatch identity before entering a live provider turn."""
    if (
        record.get("state") != "running"
        or not record.get("dispatch-owner-epoch")
        or not record.get("worker-id")
        or type(record.get("attempt-epoch")) is not int
        or record["attempt-epoch"] < 1
    ):
        return None
    return {key: record[key] for key in OWNER_KEYS}


def read_captured_handoff(
    project_root: Path, request_id: str, session_id: str,
    owner: dict[str, Any] | None,
    *, acknowledged_marker: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Read durable capture authority; never infer it from a provider signal."""
    if owner is None:
        return None
    from .. import store
    from ..output import read_final_response
    from . import sessions_store

    record = store.read_record(project_root, request_id, include_output=False)
    marker = record.get("terminal-finalization")
    if marker is None and acknowledged_marker is not None:
        # Only an already-authorized local admission fence supplies this
        # snapshot, to recognize an ACK that another idle replay has won.
        marker = acknowledged_marker
    completion = record.get("completion")
    artifact = record.get("response-artifact")
    if not (
        record.get("state") == "completed" and record.get("session-id") == session_id
        and isinstance(completion, dict)
        and completion.get("source") == "operator-provider-capture"
        and isinstance(marker, dict) and marker.get("session-id") == session_id
        and marker.get("capture-owner") == owner
        and isinstance(artifact, dict) and artifact.get("request-id") == request_id
    ):
        return None
    checkpoint = marker.get("pre-clear-checkpoint")
    if not (
        isinstance(checkpoint, dict)
        and checkpoint.get("unresolved-turn-id") == request_id
        and checkpoint.get("unresolved-turn-pending") is True
        and checkpoint.get("submission-attempt-id")
        and checkpoint.get("prompt-text-digest")
        and "expected-session-binding" in marker
    ):
        return None
    session = sessions_store.read_session_record(project_root, session_id)
    metadata = sessions_store.session_provider_metadata(session)
    if (
        session.get("binding") != marker["expected-session-binding"]
        or metadata.get("unresolved-turn-pending") is not False
        or metadata.get("unresolved-turn-id")
    ):
        return None
    read_final_response(project_root, request_id, artifact)
    return {"marker": marker, "checkpoint": checkpoint, "session-metadata": metadata}


def acknowledge_captured_handoff(
    project_root: Path, request_id: str, marker: dict[str, Any],
) -> bool:
    """Retire only this marker after exact local memory reconciliation."""
    from .. import store
    from ..output import read_final_response
    from ..store._shared import _request_lock
    from . import sessions_store

    with _request_lock(project_root, request_id):
        record = store.read_record(project_root, request_id, include_output=False)
        current_marker = record.get("terminal-finalization")
        checkpoint = marker.get("pre-clear-checkpoint")
        artifact = record.get("response-artifact")
        if (
            record.get("state") != "completed"
            or record.get("session-id") != marker.get("session-id")
            or (record.get("completion") or {}).get("source") != "operator-provider-capture"
            or current_marker not in (None, marker)
            or not isinstance(checkpoint, dict) or checkpoint.get("unresolved-turn-id") != request_id
            or "expected-session-binding" not in marker
            or not isinstance(artifact, dict) or artifact.get("request-id") != request_id
        ):
            return False
        with sessions_store._ordered_session_mutation_lock(project_root, marker["session-id"]):
            session = sessions_store.read_session_record(project_root, marker["session-id"])
            metadata = sessions_store.session_provider_metadata(session)
            if (
                session.get("binding") != marker.get("expected-session-binding")
                or metadata.get("unresolved-turn-pending") is not False
                or metadata.get("unresolved-turn-id")
            ):
                return False
            try:
                read_final_response(project_root, request_id, artifact)
            except Exception:  # noqa: BLE001 - no valid artifact means no handoff ACK
                return False
            if current_marker is None:
                # Another exact acknowledgment won. Re-prove the durable
                # result and current cleared binding, without another write.
                return True
            updated = dict(record)
            updated.pop("terminal-finalization", None)
            updated["updated-at"] = now_iso_z()
            updated["revision"] = int(record["revision"]) + 1
            store.write_record(project_root, updated)
    return True


def reconcile_idle_captured_handoff(project_root: Path, request_id: str) -> bool:
    """Replay memory handoff only outside request/session mutation locks."""
    from .. import store
    from .sessions import peek_session_runtime

    record = store.read_record(project_root, request_id, include_output=False)
    marker = record.get("terminal-finalization")
    if not isinstance(marker, dict):
        return False
    runtime = peek_session_runtime()
    if runtime is None:
        return False
    try:
        authority = read_captured_handoff(
            project_root, request_id, str(marker.get("session-id") or ""), marker.get("capture-owner"),
        )
    except Exception:  # noqa: BLE001 - retain marker; status reads must remain available
        return False
    if authority is None:
        return False
    if not runtime.synchronize_cleared_predecessor_checkpoint(
        marker["session-id"], request_id,
        expected_metadata=authority["checkpoint"],
        persisted_session_metadata=authority["session-metadata"],
    ):
        return False
    return acknowledge_captured_handoff(project_root, request_id, marker)
