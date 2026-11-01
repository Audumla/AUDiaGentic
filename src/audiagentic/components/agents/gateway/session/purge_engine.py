"""Policy-driven session-lineage purge for one session (SH32-B): claim, plan, delete, resumable.

Sequence for a session that is not yet being deleted: check eligibility; claim it under the generation
fence (so resume and continuation admission are refused from now on); recheck eligibility under the
claim and release it if anything blocks; record the deletion plan (request ids and the policy digest)
on the claim and mark destruction as begun; then delete through the one shared lineage deletion. From
the moment destruction begins the claim is never released: a crash leaves the session record (deleted
last) carrying the plan, and replaying the same operation resumes it. A session that is already gone is
``unchanged``, never ``purged``: only this operation finishing the deletion it owns is success.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _result(session_id: str, outcome: str, reason: str | None = None) -> dict[str, Any]:
    result = {"session-id": session_id, "outcome": outcome}
    if reason:
        result["reason"] = reason
    return result


def _closure(project_root: Path, session_id: str, record: dict[str, Any]) -> set[str]:
    """Every request that belongs to this session's lineage, from its record and a scan of the requests."""
    from audiagentic.components.agents.gateway import store
    from audiagentic.components.agents.gateway.session import sessions_store

    ids = set(sessions_store.session_request_ids(record))
    for request in store.list_records(project_root, include_output=False):
        if request.get("session-id") == session_id:
            ids.add(str(request.get("request-id")))
    return ids


def purge_session_under_policy(
    project_root: Path, session_id: str, *, operation_id: str, policy: Any, now: datetime | None = None,
) -> dict[str, Any]:
    """Purge one session under the machine policy; returns ``purged``, ``blocked`` or ``unchanged``."""
    from audiagentic.components.agents.agents_paths import (
        gateway_request_maintenance_lock_path,
        gateway_retention_lock_path,
        gateway_session_maintenance_lock_path,
    )
    from audiagentic.components.agents.gateway.session import sessions_store
    from audiagentic.components.agents.gateway.session.lineage_delete import delete_session_lineage
    from audiagentic.components.agents.gateway.session.purge_eligibility import session_blocker
    from audiagentic.components.agents.gateway.session.sessions import peek_session_runtime
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.system.process import StartupLock

    now = now or datetime.now(UTC)

    def live_ids() -> set[str]:
        runtime = peek_session_runtime()
        return set(runtime.live_session_ids()) if runtime is not None else set()

    def blocker(record: dict[str, Any]) -> str | None:
        return session_blocker(project_root, session_id, record, sessions_store.list_session_records(project_root),
                               live_ids(), policy, now, own_operation=operation_id)

    try:
        record = sessions_store.read_session_record(project_root, session_id)
    except AudiaGenticError:
        return _result(session_id, "unchanged", "session-not-found")
    claim = record.get("retention-claim")
    resuming = claim is not None and claim.get("operation-id") == operation_id and claim.get("stage") == "deleting"
    if not resuming:
        if not policy.available or not policy.session_purge_enabled:
            return _result(session_id, "blocked", "policy-disabled")
        reason = blocker(record)
        if reason:
            return _result(session_id, "blocked", reason)
        record = sessions_store.claim_retention(project_root, session_id, operation_id=operation_id)
        reason = blocker(record)  # recheck under the claim, before anything is destroyed
        closure = _closure(project_root, session_id, record)
        if reason:
            sessions_store.release_retention_claim(project_root, session_id, operation_id=operation_id)
            return _result(session_id, "blocked", reason)
        record = sessions_store.begin_retention_deletion(
            project_root, session_id, operation_id=operation_id,
            request_ids=sorted(closure), policy_digest=policy.digest,
        )
    plan_ids = set(record["retention-claim"]["plan"]["request-ids"])
    ids = plan_ids | _closure(project_root, session_id, record)
    from contextlib import ExitStack

    with ExitStack() as fences:
        fences.enter_context(StartupLock(gateway_session_maintenance_lock_path(project_root, session_id)))
        for request_id in sorted(ids):
            fences.enter_context(StartupLock(gateway_request_maintenance_lock_path(project_root, request_id)))
        with StartupLock(gateway_retention_lock_path(project_root)):
            delete_session_lineage(project_root, session_id, ids, record, strict=True)
    return _result(session_id, "purged")
