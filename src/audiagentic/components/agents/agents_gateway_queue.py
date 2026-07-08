"""Agent LLM Gateway per-profile queue and concurrency manager (AG09).

In-process only — a worker thread pool per profile, gated by a semaphore sized
from the profile's params. Persisted request state (agents_gateway_store) is
the durable record; this manager is the in-memory scheduling layer on top of
it. Process lifetime caveat: if the host process exits, queued/running records
remain in the store but no worker will resume them (see AG13 for a startup
reconciliation follow-up — out of scope for this slice, same call the plan
item makes for durability).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)


_TERMINAL_EVENT_SUFFIXES = {"completed", "failed", "cancelled", "rejected"}


def _publish_lifecycle_event(event_suffix: str, record: dict[str, Any]) -> None:
    """Publish an agents.llm.<event_suffix> lifecycle event for any gateway
    request (MCP-submitted or event-triggered — this is the single choke
    point for every request, so listeners see a complete lifecycle regardless
    of origin). correlation_id/subject are auto-extracted by EventEnvelope
    from whatever the record's own metadata carries (AG12 spec).

    Terminal events additionally carry provider-id/model-id/error/attempt_count
    so an observer can understand what happened without reading record.json
    (RV31 finding). Never raises — a misbehaving subscriber or an
    uninitialized event bus must not crash the worker thread driving dispatch
    (RV38 finding); failures are logged and swallowed.
    """
    from audiagentic.foundation.event import get_bus

    payload: dict[str, Any] = {
        "request-id": record["request-id"],
        "agent-profile-id": record["agent-profile-id"],
        "state": record["state"],
    }
    if event_suffix in _TERMINAL_EVENT_SUFFIXES:
        payload["provider-id"] = record.get("provider-id")
        payload["model-id"] = record.get("model-id")
        payload["error"] = record.get("error")
        payload["attempt_count"] = len(record.get("attempts") or [])

    try:
        get_bus().publish(f"agents.llm.{event_suffix}", payload, metadata=record.get("metadata", {}))
    except Exception:  # noqa: BLE001
        logger.error(
            "failed to publish gateway lifecycle event", extra={"request-id": record["request-id"], "event": event_suffix},
            exc_info=True,
        )

RequestRunner = Callable[[Path, dict[str, Any]], dict[str, Any]]
"""Callable that dispatches one gateway request record and returns the same
record (or an updated copy) transitioned to a terminal state. Injected so the
queue can be tested with a deterministic fake, independent of AG10's real
provider dispatch."""


def _params_get(params: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in params:
            return params[key]
    return None


def resolve_max_concurrency(params: dict[str, Any]) -> int:
    """Resolve params.max-concurrency (or max_concurrency); default 1, minimum 1.

    Raises on a present-but-invalid value rather than silently falling back to
    the default — a typo'd key or wrong type should be loud, not silently
    treated as max_concurrency=1 (RV19 finding on AG09).
    """
    value = _params_get(params, "max-concurrency", "max_concurrency")
    if value is None:
        return 1
    if not isinstance(value, int) or isinstance(value, bool):
        raise AudiaGenticError(
            code="VAL-AGW-020",
            kind="agents",
            message="agent profile params.max-concurrency must be an integer",
            details={"value": value},
        )
    if value < 1:
        raise AudiaGenticError(
            code="VAL-AGW-021",
            kind="agents",
            message="agent profile params.max-concurrency must be >= 1",
            details={"value": value},
        )
    return value


def resolve_queue_max_size(params: dict[str, Any], max_concurrency: int) -> int:
    """Resolve params.queue-max-size (or queue_max_size); default max(8, max_concurrency*2)."""
    value = _params_get(params, "queue-max-size", "queue_max_size")
    if value is None:
        return max(8, max_concurrency * 2)
    if not isinstance(value, int) or isinstance(value, bool):
        raise AudiaGenticError(
            code="VAL-AGW-022",
            kind="agents",
            message="agent profile params.queue-max-size must be an integer",
            details={"value": value},
        )
    if value < 1:
        raise AudiaGenticError(
            code="VAL-AGW-023",
            kind="agents",
            message="agent profile params.queue-max-size must be >= 1",
            details={"value": value},
        )
    return value


def resolve_fallback_profile_ids(params: dict[str, Any]) -> list[str]:
    """Resolve params.fallback-profile-ids (or fallback_profile_ids); default []."""
    value = _params_get(params, "fallback-profile-ids", "fallback_profile_ids")
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise AudiaGenticError(
            code="VAL-AGW-024",
            kind="agents",
            message="agent profile params.fallback-profile-ids must be a list of strings",
            details={"value": value},
        )
    return list(value)


class _ProfileQueue:
    """Bookkeeping for one agent-profile's FIFO queue and concurrency gate."""

    def __init__(self, max_concurrency: int, queue_max_size: int) -> None:
        self.max_concurrency = max_concurrency
        self.queue_max_size = queue_max_size
        self.lock = threading.Lock()
        self.pending: deque[str] = deque()
        self.running: set[str] = set()
        self.cancel_requested: set[str] = set()


class GatewayQueueManager:
    """Per-profile FIFO queues with strict concurrency, cancel, and wait.

    One manager instance is expected to live for the lifetime of the hosting
    process (module-level singleton in agents_gateway_api). Not safe to share
    across processes — see the module docstring's durability caveat.
    """

    def __init__(self) -> None:
        self._profiles: dict[str, _ProfileQueue] = {}
        self._manager_lock = threading.Lock()

    def _profile_queue(self, agent_profile_id: str, params: dict[str, Any]) -> _ProfileQueue:
        with self._manager_lock:
            pq = self._profiles.get(agent_profile_id)
            if pq is None:
                max_concurrency = resolve_max_concurrency(params)
                queue_max_size = resolve_queue_max_size(params, max_concurrency)
                pq = _ProfileQueue(max_concurrency, queue_max_size)
                self._profiles[agent_profile_id] = pq
            return pq

    def enqueue(
        self,
        project_root: Path,
        record: dict[str, Any],
        params: dict[str, Any],
        runner: RequestRunner,
    ) -> dict[str, Any]:
        """Accept a queued record, enqueueing it if capacity exists.

        Returns the (possibly rejected) record. The record must already be
        persisted in 'queued' state by the caller (agents_gateway_api).
        """
        request_id = record["request-id"]
        agent_profile_id = record["agent-profile-id"]
        pq = self._profile_queue(agent_profile_id, params)

        # Lifecycle event publish is SYNC dispatch — a subscriber that calls
        # back into cancel()/enqueue() for the same profile would try to
        # re-acquire pq.lock and deadlock (threading.Lock is not reentrant).
        # Keep the critical section limited to the pending-deque mutation
        # itself; do all I/O and event publish after releasing the lock (RV31).
        with pq.lock:
            queue_full = len(pq.pending) >= pq.queue_max_size
            if not queue_full:
                pq.pending.append(request_id)
                pending_count = len(pq.pending)

        if queue_full:
            logger.info(
                "gateway request rejected: queue full",
                extra={"request-id": request_id, "agent-profile-id": agent_profile_id, "queue-max-size": pq.queue_max_size},
            )
            rejected = store.transition_record(
                project_root, request_id, "rejected",
                updates={"error": {
                    "code": "VAL-AGW-025",
                    "message": f"queue full for profile {agent_profile_id!r} (max {pq.queue_max_size})",
                    "kind": "agents",
                }},
            )
            store.record_gateway_timeline(
                project_root,
                request_id,
                "queue.rejected",
                state=rejected["state"],
                attributes={
                    "agent-profile-id": agent_profile_id,
                    "queue-max-size": pq.queue_max_size,
                    "correlation_id": (rejected.get("metadata") or {}).get("correlation_id"),
                },
            )
            _publish_lifecycle_event("rejected", rejected)
            return rejected

        logger.info(
            "gateway request queued",
            extra={"request-id": request_id, "agent-profile-id": agent_profile_id, "pending": pending_count},
        )
        store.record_gateway_timeline(
            project_root,
            request_id,
            "queue.queued",
            state=record["state"],
            attributes={
                "agent-profile-id": agent_profile_id,
                "pending": pending_count,
                "correlation_id": (record.get("metadata") or {}).get("correlation_id"),
            },
        )
        _publish_lifecycle_event("queued", record)

        self._drain(project_root, agent_profile_id, pq, params, runner)
        return store.read_record(project_root, request_id)

    def _drain(
        self,
        project_root: Path,
        agent_profile_id: str,
        pq: _ProfileQueue,
        params: dict[str, Any],
        runner: RequestRunner,
    ) -> None:
        """Start worker threads for as many pending requests as capacity allows."""
        while True:
            with pq.lock:
                if len(pq.running) >= pq.max_concurrency or not pq.pending:
                    return
                request_id = pq.pending.popleft()
                pq.running.add(request_id)
            thread = threading.Thread(
                target=self._run_one,
                args=(project_root, agent_profile_id, pq, request_id, params, runner),
                daemon=True,
                name=f"gateway-{agent_profile_id}-{request_id}",
            )
            thread.start()

    def _run_one(
        self,
        project_root: Path,
        agent_profile_id: str,
        pq: _ProfileQueue,
        request_id: str,
        params: dict[str, Any],
        runner: RequestRunner,
    ) -> None:
        try:
            if request_id in pq.cancel_requested:
                logger.info("gateway request cancelled before dispatch", extra={"request-id": request_id})
                cancelled = store.transition_record(project_root, request_id, "cancelled")
                store.record_gateway_timeline(project_root, request_id, "queue.cancelled-before-dispatch", state="cancelled")
                _publish_lifecycle_event("cancelled", cancelled)
                return
            record = store.transition_record(
                project_root, request_id, "running",
                updates={"started-at": now_iso_z()},
            )
            logger.info("gateway request running", extra={"request-id": request_id, "agent-profile-id": agent_profile_id})
            store.record_gateway_timeline(
                project_root,
                request_id,
                "queue.started",
                state=record["state"],
                attributes={
                    "agent-profile-id": agent_profile_id,
                    "correlation_id": (record.get("metadata") or {}).get("correlation_id"),
                },
            )
            _publish_lifecycle_event("started", record)
            try:
                result = runner(project_root, record)
                logger.info(
                    "gateway request finished",
                    extra={"request-id": request_id, "state": result.get("state") if isinstance(result, dict) else None},
                )
                if isinstance(result, dict):
                    store.record_gateway_timeline(
                        project_root,
                        request_id,
                        "queue.finished",
                        state=result.get("state"),
                        attributes={
                            "agent-profile-id": agent_profile_id,
                            "correlation_id": (result.get("metadata") or {}).get("correlation_id"),
                        },
                    )
                if isinstance(result, dict) and result.get("state") in ("completed", "failed", "cancelled"):
                    _publish_lifecycle_event(result["state"], result)
            except AudiaGenticError as exc:
                logger.error("gateway request runner raised", extra={"request-id": request_id}, exc_info=True)
                current = store.read_record(project_root, request_id)
                if current["state"] == "running":
                    failed = store.transition_record(
                        project_root, request_id, "failed",
                        updates={"error": exc, "finished-at": now_iso_z()},
                    )
                    _publish_lifecycle_event("failed", failed)
            except Exception as exc:  # noqa: BLE001
                logger.error("gateway request runner raised unexpectedly", extra={"request-id": request_id}, exc_info=True)
                current = store.read_record(project_root, request_id)
                if current["state"] == "running":
                    failed = store.transition_record(
                        project_root, request_id, "failed",
                        updates={"error": exc, "finished-at": now_iso_z()},
                    )
                    _publish_lifecycle_event("failed", failed)
        finally:
            with pq.lock:
                pq.running.discard(request_id)
                pq.cancel_requested.discard(request_id)
            self._drain(project_root, agent_profile_id, pq, params, runner)

    def cancel(self, project_root: Path, agent_profile_id: str, request_id: str) -> dict[str, Any]:
        """Cancel a queued request, or mark a running one cancel-requested (best-effort).

        A request that is already running is NOT force-transitioned to
        'cancelled' — the runner may complete normally. Callers should not
        assume the terminal state will be 'cancelled' for a cancel issued
        against a running request (RV15 finding).
        """
        pq = self._profiles.get(agent_profile_id)
        if pq is None:
            return store.read_record(project_root, request_id)

        with pq.lock:
            if request_id in pq.pending:
                pq.pending.remove(request_id)
                removed_from_queue = True
            else:
                removed_from_queue = False
            is_running = request_id in pq.running
            if is_running:
                pq.cancel_requested.add(request_id)

        if removed_from_queue:
            logger.info("gateway request cancelled (was queued)", extra={"request-id": request_id})
            return store.transition_record(project_root, request_id, "cancelled")
        if is_running:
            # Persisted so the intent is observable (get/wait) and so the
            # dispatch retry/fallback loop can see it across process/module
            # boundaries — the in-memory cancel_requested set alone is not
            # enough once the record is inspected from outside this manager.
            logger.info("gateway request cancel-requested (running)", extra={"request-id": request_id})
            return store.mark_cancel_requested(project_root, request_id)
        return store.read_record(project_root, request_id)

    def wait(self, project_root: Path, request_id: str, timeout_seconds: float | None) -> dict[str, Any]:
        """Block until the request reaches a terminal state or timeout elapses.

        Polls the persisted record rather than an in-memory signal so it works
        regardless of which GatewayQueueManager instance (if any) is driving
        the request — including calls made after an async submit from a
        separate process invocation.
        """
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        poll_interval = 0.05
        while True:
            record = store.read_record(project_root, request_id)
            if record["state"] in store.TERMINAL_STATES:
                return record
            if deadline is not None and time.monotonic() >= deadline:
                return record
            time.sleep(poll_interval)

    def queue_depth(self, agent_profile_id: str) -> dict[str, int]:
        pq = self._profiles.get(agent_profile_id)
        if pq is None:
            return {"pending": 0, "running": 0, "max_concurrency": 0}
        with pq.lock:
            return {
                "pending": len(pq.pending),
                "running": len(pq.running),
                "max_concurrency": pq.max_concurrency,
            }

    def all_queue_depths(self) -> dict[str, dict[str, int]]:
        """Return queue_depth() for every profile that has ever had a request
        submitted in this process (used by the component status hook)."""
        with self._manager_lock:
            profile_ids = list(self._profiles)
        return {profile_id: self.queue_depth(profile_id) for profile_id in profile_ids}
