"""Agent LLM Gateway public API — async submit, blocking run, status, wait, cancel.

Thin orchestration over agents_gateway_store (persistence), agents_gateway_queue
(per-profile concurrency), and agents_gateway_dispatch (provider dispatch/retry/
fallback). One GatewayQueueManager instance per process (module-level) — see
its docstring for the process-lifetime caveat.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_dispatch as dispatch
from audiagentic.components.agents import agents_gateway_queue as queue_mod
from audiagentic.components.agents import agents_gateway_store as store

# A blocking MCP tool call must not hold the connection indefinitely — the
# client-side transport typically has its own 30-60s timeout. Cap requested
# blocking waits server-side and return a 'running'/'queued' status rather
# than hang (RV17 finding on AG11).
MAX_BLOCKING_TIMEOUT_SECONDS = 300.0

_QUEUE_MANAGER = queue_mod.GatewayQueueManager()


def _resolve_profile_for_submit(project_root: Path, agent_profile_id: str | None) -> dict[str, Any]:
    from audiagentic.components.agents.agents_api import resolve_default_profile, resolve_profile

    if agent_profile_id:
        return resolve_profile(project_root, agent_profile_id)
    return resolve_default_profile(project_root)


def submit_llm_request(
    project_root: Path,
    *,
    agent_profile_id: str | None = None,
    prompt_body: str | None = None,
    mode: str = "async",
    timeout_seconds: float | None = None,
    fallback_profile_ids: list[str] | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit a gateway request. Returns immediately with request-id and initial state
    unless mode='blocking', in which case it waits for a terminal result (see run_llm_request).
    """
    profile = _resolve_profile_for_submit(project_root, agent_profile_id)
    resolved_profile_id = profile["profile_id"]
    params = profile.get("params", {})

    resolved_fallback_ids = (
        fallback_profile_ids
        if fallback_profile_ids is not None
        else queue_mod.resolve_fallback_profile_ids(params)
    )

    record = store.build_record(
        agent_profile_id=resolved_profile_id,
        prompt_body=prompt_body,
        mode=mode,
        timeout_seconds=timeout_seconds,
        fallback_profile_ids=resolved_fallback_ids,
        source=source,
        metadata=metadata,
    )
    store.write_record(project_root, record)
    record = _QUEUE_MANAGER.enqueue(project_root, record, params, dispatch.dispatch_request)

    if mode == "blocking":
        wait_timeout = min(timeout_seconds, MAX_BLOCKING_TIMEOUT_SECONDS) if timeout_seconds else MAX_BLOCKING_TIMEOUT_SECONDS
        return _QUEUE_MANAGER.wait(project_root, record["request-id"], wait_timeout)
    return record


def get_llm_request(project_root: Path, request_id: str) -> dict[str, Any]:
    """Return the current persisted state of a gateway request."""
    return store.read_record(project_root, request_id)


def wait_llm_request(project_root: Path, request_id: str, timeout_seconds: float | None = None) -> dict[str, Any]:
    """Block until a request reaches a terminal state or the (capped) timeout elapses."""
    capped = min(timeout_seconds, MAX_BLOCKING_TIMEOUT_SECONDS) if timeout_seconds else MAX_BLOCKING_TIMEOUT_SECONDS
    return _QUEUE_MANAGER.wait(project_root, request_id, capped)


def cancel_llm_request(project_root: Path, request_id: str) -> dict[str, Any]:
    """Cancel a queued request, or best-effort mark a running one cancel-requested.

    See GatewayQueueManager.cancel — a running request is not force-terminated;
    its persisted terminal state reflects what actually happened.
    """
    record = store.read_record(project_root, request_id)
    return _QUEUE_MANAGER.cancel(project_root, record["agent-profile-id"], request_id)


def run_llm_request(
    project_root: Path,
    *,
    agent_profile_id: str | None = None,
    prompt_body: str | None = None,
    timeout_seconds: float | None = None,
    fallback_profile_ids: list[str] | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Submit and block until a terminal result or timeout. Not for event-triggered
    paths (AG12 handles those asynchronously through lifecycle events)."""
    return submit_llm_request(
        project_root,
        agent_profile_id=agent_profile_id,
        prompt_body=prompt_body,
        mode="blocking",
        timeout_seconds=timeout_seconds,
        fallback_profile_ids=fallback_profile_ids,
        source=source,
        metadata=metadata,
    )


def queue_status(agent_profile_id: str) -> dict[str, Any]:
    """Return queue depth/running/max-concurrency for one profile (used by AG13 status)."""
    return _QUEUE_MANAGER.queue_depth(agent_profile_id)


def gateway_status() -> dict[str, Any]:
    """Return queue depth/running/max-concurrency for every profile with an
    active queue in THIS process only (in-memory — empty after a restart even
    if persisted records exist). Prefer gateway_overview() for a complete
    picture; kept for backward compatibility with existing callers."""
    return _QUEUE_MANAGER.all_queue_depths()


def list_llm_requests(
    project_root: Path,
    *,
    state: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """List persisted gateway requests, most recently created first.

    Reads from disk (agents_gateway_store.list_records), so this reflects
    requests from any process — including ones orphaned by a restart, unlike
    the in-memory-only queue_status/gateway_status (RV33 finding).
    """
    records = store.list_records(project_root)
    if state is not None:
        records = [r for r in records if r["state"] == state]
    records.sort(key=lambda r: r["created-at"], reverse=True)
    if limit is not None:
        records = records[:limit]
    return records


def reconcile_gateway_state(project_root: Path) -> dict[str, Any]:
    """Resolve orphaned queued/running records after a process restart.

    The in-memory GatewayQueueManager cannot recover worker execution state.
    Running records become failed; queued records become rejected. Terminal
    records are ignored, making this safe to call repeatedly.
    """
    reconciled: list[dict[str, str]] = []
    for record in store.list_records(project_root):
        request_id = record["request-id"]
        if record["state"] == "running":
            updated = store.transition_record(
                project_root,
                request_id,
                "failed",
                updates={
                    "error": {
                        "code": "INT-AGW-ORPHANED",
                        "kind": "agents",
                        "message": "gateway request orphaned after process restart",
                    },
                    "finished_at": None,
                },
            )
            reconciled.append({"request-id": request_id, "state": updated["state"]})
        elif record["state"] == "queued":
            updated = store.transition_record(
                project_root,
                request_id,
                "rejected",
                updates={
                    "error": {
                        "code": "INT-AGW-ORPHANED",
                        "kind": "agents",
                        "message": "queued gateway request rejected after process restart",
                    },
                    "finished_at": None,
                },
            )
            reconciled.append({"request-id": request_id, "state": updated["state"]})
    return {"ok": True, "reconciled": reconciled}


def gateway_overview(project_root: Path) -> dict[str, Any]:
    """Operator-facing summary: persisted request counts by state (works even
    after a process restart) plus in-process queue depths for active profiles.

    Answers "what's happening with the gateway right now" without already
    knowing a request-id (RV33/RV36/RV37 finding — status/README previously
    only exposed in-memory queue depths, which are empty after a restart even
    though persisted state still shows what happened).
    """
    records = store.list_records(project_root)
    by_state: dict[str, int] = {}
    for record in records:
        by_state[record["state"]] = by_state.get(record["state"], 0) + 1
    recent_failures = [
        {"request-id": r["request-id"], "agent-profile-id": r["agent-profile-id"], "error": r.get("error")}
        for r in sorted(
            (r for r in records if r["state"] == "failed"),
            key=lambda r: r["updated-at"],
            reverse=True,
        )[:5]
    ]
    return {
        "total_requests": len(records),
        "by_state": by_state,
        "recent_failures": recent_failures,
        "queues": _QUEUE_MANAGER.all_queue_depths(),
    }
