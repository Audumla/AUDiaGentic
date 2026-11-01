"""Which closed sessions the machine session-purge policy would allow to be purged (SH32-A).

Read-only: this scans and reports; it claims nothing and deletes nothing. The clock is only
``timing.last-accepted-turn-at``; a missing or unreadable clock, an unreadable request, shared or
pinned references, a retention claim, a live runtime or any non-terminal work all BLOCK. Unknown
means BLOCK.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Closed and expired lineage only: a failed session is terminal but is not retired by policy.
PURGEABLE_SESSION_STATES = frozenset({"closed", "expired"})


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _request_blocker(project_root: Path, session_id: str, record: dict[str, Any]) -> str | None:
    from audiagentic.components.agents.gateway import store
    from audiagentic.components.agents.gateway.session import sessions_store
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    wanted = set(sessions_store.session_request_ids(record))
    for request in store.list_records(project_root, include_output=False):
        if request.get("session-id") == session_id:
            wanted.add(str(request.get("request-id")))
    for request_id in sorted(wanted):
        try:
            request = store.read_record(project_root, request_id, include_output=False)
        except AudiaGenticError:
            return "request-record-unreadable"
        except Exception:  # noqa: BLE001 - anything unreadable is unknown, and unknown blocks
            return "request-record-unreadable"
        if request.get("state") not in store.TERMINAL_STATES:
            return "session-has-active-requests"
    return None


def _shared_blocker(project_root: Path, session_id: str, request_ids: set[str], others: list[dict[str, Any]]) -> str | None:
    from audiagentic.components.agents.gateway.session import root_registry, sessions_store

    for other in others:
        if other.get("session-id") == session_id:
            continue
        if request_ids & set(sessions_store.session_request_ids(other)):
            return "request-shared-with-another-session"
    for request_id in request_ids:
        owners = set(root_registry.request_ids_for_registered_roots(project_root, request_id))
        if owners - {session_id}:
            return "request-shared-with-another-session"
    return None


def session_purge_report(project_root: Path, *, policy: Any | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Eligibility of every session in ``project_root`` under the machine policy, without mutating anything."""
    from audiagentic.components.agents.gateway.operations.retention_policy import (
        load_retention_policy,
    )
    from audiagentic.components.agents.gateway.session import sessions_store
    from audiagentic.components.agents.gateway.session.sessions import peek_session_runtime

    policy = policy or load_retention_policy()
    report: dict[str, Any] = {
        "policy": {"policy-id": policy.policy_id, "available": policy.available,
                   "session-purge-enabled": policy.session_purge_enabled,
                   "session-purge-inactivity-seconds": policy.session_purge_inactivity_seconds},
        "eligible": [], "blocked": [], "scope": "gateway-local session lineage only; remote provider conversations are never touched",
    }
    if not policy.available or not policy.session_purge_enabled:
        report["blocked"] = [{"reason": "policy-disabled"}]
        return report
    now = now or datetime.now(UTC)
    runtime = peek_session_runtime()
    live = set(runtime.live_session_ids()) if runtime is not None else set()
    records = sessions_store.list_session_records(project_root)
    for record in sorted(records, key=lambda item: str(item.get("session-id"))):
        session_id = str(record.get("session-id"))
        reason = session_blocker(project_root, session_id, record, records, live, policy, now)
        if reason is None:
            report["eligible"].append(session_id)
        else:
            report["blocked"].append({"session-id": session_id, "reason": reason})
    return report


def session_blocker(project_root: Path, session_id: str, record: dict[str, Any], records: list[dict[str, Any]],
                    live: set[str], policy: Any, now: datetime, *, own_operation: str | None = None) -> str | None:
    """The first reason this session may not be purged now, or None. A claim by ``own_operation`` is not a blocker."""
    from audiagentic.components.agents.gateway.session import sessions_store

    if record.get("state") not in PURGEABLE_SESSION_STATES:
        return "session-not-closed"
    claim = record.get("retention-claim")
    if claim is not None and claim.get("operation-id") != own_operation:
        return "retention-claimed"
    if session_id in live:
        return "session-live"
    clock = _parse((record.get("timing") or {}).get("last-accepted-turn-at"))
    if clock is None:
        return "no-accepted-turn-clock"
    if (now - clock).total_seconds() < policy.session_purge_inactivity_seconds:
        return "inactivity-below-threshold"
    blocker = _request_blocker(project_root, session_id, record)
    if blocker:
        return blocker
    return _shared_blocker(project_root, session_id, set(sessions_store.session_request_ids(record)), records)
