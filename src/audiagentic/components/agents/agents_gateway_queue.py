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

import asyncio
import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents import (
    agents_gateway_profiles as profiles_mod,
)
from audiagentic.components.agents import agents_gateway_store as store
from audiagentic.components.agents.agents_event_topics import (
    LLM_CANCELLED_TOPIC,
    LLM_COMPLETED_TOPIC,
    LLM_FAILED_TOPIC,
    LLM_INTERRUPTED_TOPIC,
    LLM_QUEUED_TOPIC,
    LLM_REJECTED_TOPIC,
    LLM_STARTED_TOPIC,
)
from audiagentic.components.agents.agents_paths import gateway_request_path
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)


_WAIT_INITIAL_BACKOFF_SECONDS = 0.05
_WAIT_MAX_BACKOFF_SECONDS = 0.5


def _record_signature(path: Path) -> tuple[int, int, int] | None:
    """Return a cheap change marker for a durable gateway record.

    Records are atomically replaced by the store.  Size plus the platform's
    modification/change timestamps gives waiters a low-cost hint that a full
    JSON read is useful, without making correctness depend on any one
    filesystem timestamp's precision.  A bounded full-read fallback remains
    below for filesystems that cannot expose a distinguishable marker.
    """
    try:
        status = path.stat()
    except OSError:
        return None
    return (status.st_size, status.st_mtime_ns, status.st_ctime_ns)


class TurnConcurrencyCallbacks:
    """Two-phase concurrency hooks called by SessionRuntime when a session turn
    actually starts and finishes on the transport. Per-request callbacks are
    stored in a thread-safe dict to support max_concurrency > 1 (AS15).

    SessionRuntime invokes the callbacks on its asyncio loop. Blocking slot
    acquisition is therefore delegated to a worker thread.
    """

    def __init__(self) -> None:
        self._callbacks: dict[
            str,
            tuple[Callable[[str], Awaitable[None]], Callable[[str], Awaitable[None]]],
        ] = {}
        self._lock = threading.Lock()

    def set_callbacks(
        self,
        request_id: str,
        on_turn_starting: Callable[[str], Awaitable[None]],
        on_turn_done: Callable[[str], Awaitable[None]],
    ) -> None:
        """Wire up the two-phase callbacks for a request. Called at _run_one dispatch time."""
        with self._lock:
            self._callbacks[request_id] = (on_turn_starting, on_turn_done)

    def clear(self, request_id: str) -> None:
        """Remove callbacks after the request completes."""
        with self._lock:
            self._callbacks.pop(request_id, None)

    async def turn_starting(self, request_id: str) -> None:
        with self._lock:
            cb = self._callbacks.get(request_id)
        if cb is not None:
            await cb[0](request_id)

    async def turn_done(self, request_id: str) -> None:
        with self._lock:
            cb = self._callbacks.get(request_id)
        if cb is not None:
            await cb[1](request_id)


_TURNCB = TurnConcurrencyCallbacks()


async def notify_turn_starting(request_id: str) -> None:
    """Wait until this session turn owns one profile compute slot."""
    await _TURNCB.turn_starting(request_id)


async def notify_turn_done(request_id: str) -> None:
    """Release the profile compute slot owned by this session turn."""
    await _TURNCB.turn_done(request_id)

_TERMINAL_EVENT_SUFFIXES = {"completed", "failed", "cancelled", "rejected", "interrupted"}

# BU02: explicit suffix→topic-constant map replaces the f-string publish.
# Each value matches a registered agents-owned topic in events.yaml.
_LIFECYCLE_SUFFIX_TOPIC_MAP: dict[str, str] = {
    "queued": LLM_QUEUED_TOPIC,
    "started": LLM_STARTED_TOPIC,
    "completed": LLM_COMPLETED_TOPIC,
    "failed": LLM_FAILED_TOPIC,
    "cancelled": LLM_CANCELLED_TOPIC,
    "rejected": LLM_REJECTED_TOPIC,
    "interrupted": LLM_INTERRUPTED_TOPIC,
}


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
    if event_suffix == "interrupted":
        recovery_info = record.get("recovery") or {}
        payload["replay_required"] = recovery_info.get("outcome") == "replay-required"

    topic = _LIFECYCLE_SUFFIX_TOPIC_MAP.get(event_suffix)
    if topic is None:
        logger.error(
            "unknown lifecycle event suffix; skipping publish",
            extra={"request-id": record["request-id"], "event": event_suffix},
        )
        return
    try:
        get_bus().publish(topic, payload, metadata=record.get("metadata", {}))
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

RequestRunnerWithContext = Callable[[Path, dict[str, Any], str | None], dict[str, Any]]
"""SH02: runner that also receives the dispatch_prompt (raw prompt body)
separately from the persisted record. The persisted record only carries
prompt_digest; dispatch needs the raw prompt for provider execution."""


@dataclass(frozen=True)
class QueuedDispatch:
    """Immutable per-request dispatch entry. Carries everything _drain/_run_one
    needs so that concurrent enqueues for the same profile never substitute
    caller context for a different request's context (SH07).

    SH07 C2: lane_key and snapshot provide gateway-owned execution identity;
    params comes from the resolved snapshot, not the caller.
    """

    request_id: str
    project_root: Path
    agent_profile_id: str
    lane_key: profiles_mod.GatewayExecutionLaneKey
    snapshot: profiles_mod.GatewayProfileSnapshot
    runner: RequestRunner
    owner_epoch: str
    service_root: Path | None


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


class _ProfileQueue:
    """Bookkeeping for one agent-profile's FIFO queue and concurrency gate.

    Session-aware concurrency (AS15): pq.running tracks all dispatched requests,
    but pq.idle tracks those that are waiting on a session turn_lock (not doing
    real compute). The concurrency gate uses active_running = running - idle so
    idle sessions don't block other profiles from making progress.
    """

    def __init__(self, max_concurrency: int, queue_max_size: int) -> None:
        self.max_concurrency = max_concurrency
        self.queue_max_size = queue_max_size
        self.lock = threading.Lock()
        self.pending: deque[QueuedDispatch] = deque()
        self.running: set[str] = set()
        self.idle: set[str] = set()
        self.cancel_requested: set[str] = set()
        self.compute_slots = threading.BoundedSemaphore(max_concurrency)

    def active_running(self) -> int:
        """Count of requests actually consuming compute (not waiting on session locks)."""
        return len(self.running) - len(self.idle)


class GatewayQueueManager:
    """Per-profile FIFO queues with strict concurrency, cancel, and wait.

    One manager instance is expected to live for the lifetime of the hosting
    process (module-level singleton in agents_gateway_api). Not safe to share
    across processes — see the module docstring's durability caveat.
    """

    def __init__(self) -> None:
        self._lanes: dict[tuple[str, str, str], _ProfileQueue] = {}
        self._manager_lock = threading.Lock()

    def _execution_lane(self, snapshot: profiles_mod.GatewayProfileSnapshot) -> _ProfileQueue:
        lane_key_tuple = (snapshot.profile_id, snapshot.generation, snapshot.config_digest)
        with self._manager_lock:
            pq = self._lanes.get(lane_key_tuple)
            if pq is None:
                pq = _ProfileQueue(snapshot.max_concurrency, snapshot.queue_max_size)
                self._lanes[lane_key_tuple] = pq
            return pq

    def enqueue(
        self,
        project_root: Path,
        record: dict[str, Any],
        params: dict[str, Any],
        runner: RequestRunner,
        *,
        dispatch_owner_epoch: str | None = None,
        dispatch_service_root: Path | None = None,
    ) -> dict[str, Any]:
        """Accept a queued record, enqueueing it if capacity exists.

        Uses the snapshot identity persisted in the record at admission time
        (SH07 C2).  This prevents project-local params from re-defining lane
        limits — the gateway-owned snapshot is authoritative.

        Returns the (possibly rejected) record. The record must already be
        persisted in 'queued' state by the caller (agents_gateway_api).
        """
        request_id = record["request-id"]
        agent_profile_id = record["agent-profile-id"]

        # SH07 C2: reconstruct snapshot from record's admission-time identity.
        # The record was built with snapshot fields by submit_llm_request;
        # using them here prevents any project-local params override.
        snapshot = profiles_mod.snapshot_from_record(record)
        if snapshot is None:
            # Pre-SH07 C2 record or test path: derive from caller params as fallback.
            resolved_provider_id = params.get("provider_id") or params.get("provider-id", "")
            resolved_model_id = params.get("model_id") or params.get("model-id")
            snapshot = profiles_mod.snapshot_from_resolved_profile(
                profile_id=agent_profile_id,
                provider_id=resolved_provider_id,
                model_id=resolved_model_id,
                params=params,
            )
        lane_key = snapshot.lane_key()

        # SH07 C2: validate snapshot is current before admission.
        # A stale snapshot means the gateway profile changed; reject with
        # CON-AGW-101 resubmit-required. The default AlwaysCurrentValidator
        # preserves existing behavior; tests inject a validator to simulate
        # generation changes.
        validator = profiles_mod.get_snapshot_validator()
        if not validator.validate_snapshot_current(snapshot):
            logger.info(
                "gateway request rejected: stale profile snapshot",
                extra={"request-id": request_id, "agent-profile-id": agent_profile_id, "lane-key": lane_key.public_id()},
            )
            rejected = store.transition_record(
                project_root, request_id, "rejected",
                updates={"error": {
                    "code": "CON-AGW-101",
                    "message": "gateway profile changed; resubmit required",
                    "kind": "agents",
                }},
            )
            store.record_gateway_timeline(
                project_root,
                request_id,
                "queue.rejected-stale-snapshot",
                state=rejected["state"],
                attributes={
                    "agent-profile-id": agent_profile_id,
                    "lane-key": lane_key.public_id(),
                    "gateway-profile-generation": snapshot.generation,
                    "correlation_id": (rejected.get("metadata") or {}).get("correlation_id"),
                },
            )
            _publish_lifecycle_event("rejected", rejected)
            return rejected

        owner_epoch = dispatch_owner_epoch or f"local-{uuid.uuid4().hex}"
        pq = self._execution_lane(snapshot)

        # Lifecycle event publish is SYNC dispatch — a subscriber that calls
        # back into cancel()/enqueue() for the same profile would try to
        # re-acquire pq.lock and deadlock (threading.Lock is not reentrant).
        # Keep the critical section limited to the pending-deque mutation
        # itself; do all I/O and event publish after releasing the lock (RV31).
        entry = QueuedDispatch(
            request_id=request_id,
            project_root=project_root,
            agent_profile_id=agent_profile_id,
            lane_key=lane_key,
            snapshot=snapshot,
            runner=runner,
            owner_epoch=owner_epoch,
            service_root=dispatch_service_root,
        )
        pending_count = 0
        with pq.lock:
            queue_full = len(pq.pending) >= pq.queue_max_size
            if not queue_full:
                pq.pending.append(entry)
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

        self._drain(pq)
        return store.read_record(project_root, request_id)

    def _drain(self, pq: _ProfileQueue) -> None:
        """Start worker threads for as many pending requests as capacity allows.

        AS15: uses active_running() (running - idle) so that session requests
        waiting on turn_lock don't block other sessions from making progress.
        """
        while True:
            with pq.lock:
                if pq.active_running() >= pq.max_concurrency or not pq.pending:
                    return
                entry = pq.pending.popleft()
                request_id = entry.request_id
                pq.running.add(request_id)
            thread = threading.Thread(
                target=self._run_one,
                args=(pq, entry),
                daemon=True,
                name=f"gateway-{entry.agent_profile_id}-{request_id}",
            )
            thread.start()

    def _run_one(self, pq: _ProfileQueue, entry: QueuedDispatch) -> None:
        project_root = entry.project_root
        agent_profile_id = entry.agent_profile_id
        request_id = entry.request_id
        owner_epoch = entry.owner_epoch
        runner = entry.runner
        service_root = entry.service_root

        is_session = False
        non_session_slot_held = False

        try:
            if request_id in pq.cancel_requested:
                logger.info("gateway request cancelled before dispatch", extra={"request-id": request_id})
                cancelled = store.cancel_queued_or_mark_requested(project_root, request_id)
                if cancelled["state"] == "cancelled":
                    store.record_gateway_timeline(project_root, request_id, "queue.cancelled-before-dispatch", state="cancelled")
                    _publish_lifecycle_event("cancelled", cancelled)
                return

            # SH07 C2: validate snapshot is still current before dispatch.
            # Queued work must not silently drain under old profile limits;
            # if the gateway profile changed while this request was pending,
            # reject it terminally with CON-AGW-101 resubmit-required.
            validator = profiles_mod.get_snapshot_validator()
            if not validator.validate_snapshot_current(entry.snapshot):
                logger.info(
                    "gateway request rejected before dispatch: stale profile snapshot",
                    extra={"request-id": request_id, "lane-key": entry.lane_key.public_id()},
                )
                rejected = store.transition_record(
                    project_root, request_id, "rejected",
                    updates={"error": {
                        "code": "CON-AGW-101",
                        "message": "gateway profile changed; resubmit required",
                        "kind": "agents",
                    }},
                )
                store.record_gateway_timeline(
                    project_root,
                    request_id,
                    "queue.rejected-stale-dispatch",
                    state=rejected["state"],
                    attributes={
                        "agent-profile-id": agent_profile_id,
                        "lane-key": entry.lane_key.public_id(),
                        "gateway-profile-generation": entry.snapshot.generation,
                    },
                )
                _publish_lifecycle_event("rejected", rejected)
                return

            current = store.read_record(project_root, request_id)
            try:
                claimed = store.claim_dispatch(
                    project_root, request_id, owner_epoch=owner_epoch,
                    expected_revision=current["revision"],
                    service_root=service_root,
                )
            except AudiaGenticError as exc:
                # Cancellation may linearize after this worker has dequeued the
                # request but before its durable claim is written.  That makes
                # this claim deliberately stale: the cancellation is already
                # the authoritative terminal outcome, so this worker only has
                # cleanup left to do.  Keep every other claim conflict loud --
                # it is evidence of an ownership/revision bug, not a retry
                # opportunity.
                latest = store.read_record(project_root, request_id)
                if (
                    exc.code in {"CON-AGW-071", "CON-AGW-083"}
                    and latest["state"] == "cancelled"
                ):
                    logger.info(
                        "gateway dispatch claim superseded by durable cancellation",
                        extra={"request-id": request_id},
                    )
                    _publish_lifecycle_event("cancelled", latest)
                    return
                raise
            if claimed["state"] != "queued":
                return
            record = store.start_owned_attempt(
                project_root, request_id, owner_epoch=owner_epoch,
                worker_id=f"worker_{uuid.uuid4().hex[:16]}",
                expected_revision=claimed["revision"],
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

            # AS15: two-phase concurrency for session requests.
            # Detect session request early to set up callbacks.
            is_session = bool(record.get("session-id") or record.get("session-keep-alive"))
            if is_session:
                with pq.lock:
                    pq.idle.add(request_id)

                session_slot_held = False

                async def _on_turn_starting(rid: str) -> None:
                    nonlocal session_slot_held
                    await asyncio.to_thread(pq.compute_slots.acquire)
                    with pq.lock:
                        session_slot_held = True
                        pq.idle.discard(rid)

                async def _on_turn_done(rid: str) -> None:
                    nonlocal session_slot_held
                    with pq.lock:
                        release_slot = session_slot_held
                        session_slot_held = False
                        pq.idle.add(rid)
                    if release_slot:
                        pq.compute_slots.release()
                    self._drain(pq)

                _TURNCB.set_callbacks(request_id, _on_turn_starting, _on_turn_done)
                # This worker is waiting at the session/turn boundary, so let
                # another request reach the same bounded compute gate.
                self._drain(pq)
            else:
                pq.compute_slots.acquire()
                non_session_slot_held = True

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
                    failed = store.transition_owned_terminal(
                        project_root, request_id, "failed",
                        updates={"error": exc, "finished-at": now_iso_z()},
                        owner_epoch=record["dispatch-owner-epoch"],
                        worker_id=record["worker-id"],
                        attempt_epoch=record["attempt-epoch"],
                    )
                    _publish_lifecycle_event("failed", failed)
            except Exception as exc:  # noqa: BLE001
                logger.error("gateway request runner raised unexpectedly", extra={"request-id": request_id}, exc_info=True)
                current = store.read_record(project_root, request_id)
                if current["state"] == "running":
                    failed = store.transition_owned_terminal(
                        project_root, request_id, "failed",
                        updates={"error": exc, "finished-at": now_iso_z()},
                        owner_epoch=record["dispatch-owner-epoch"],
                        worker_id=record["worker-id"],
                        attempt_epoch=record["attempt-epoch"],
                    )
                    _publish_lifecycle_event("failed", failed)
        finally:
            if non_session_slot_held:
                pq.compute_slots.release()
            with pq.lock:
                pq.running.discard(request_id)
                pq.idle.discard(request_id)
                pq.cancel_requested.discard(request_id)
            _TURNCB.clear(request_id)
            self._drain(pq)

    def _find_lane_for_request(self, agent_profile_id: str, request_id: str) -> _ProfileQueue | None:
        """Scan lanes to find the queue that contains or tracks this request.

        Backward-compat: caller only knows agent_profile_id, not the full lane key.
        """
        with self._manager_lock:
            for lane_key_tuple, pq in self._lanes.items():
                if lane_key_tuple[0] == agent_profile_id:
                    # Profile matches; check if this request is tracked here
                    with pq.lock:
                        if request_id in pq.running or any(
                            e.request_id == request_id for e in pq.pending
                        ):
                            return pq
        return None

    def cancel(self, project_root: Path, agent_profile_id: str, request_id: str) -> dict[str, Any]:
        """Cancel a queued request, or mark a running one cancel-requested (best-effort).

        A request that is already running is NOT force-transitioned to
        'cancelled' — the runner may complete normally. Callers should not
        assume the terminal state will be 'cancelled' for a cancel issued
        against a running request (RV15 finding).
        """
        pq = self._find_lane_for_request(agent_profile_id, request_id)
        if pq is None:
            # A remote service/process can own the in-memory queue.  Durable
            # cancellation still has to reach the record even when this local
            # manager has no profile queue.
            return store.cancel_queued_or_mark_requested(project_root, request_id)

        with pq.lock:
            # Search deque for matching entry (pending entries are QueuedDispatch objects)
            removed_from_queue = False
            for i, e in enumerate(pq.pending):
                if e.request_id == request_id:
                    del pq.pending[i]
                    removed_from_queue = True
                    break
            is_running = request_id in pq.running
            if is_running:
                pq.cancel_requested.add(request_id)

        if removed_from_queue or is_running:
            # The durable record is the linearization point.  A request may
            # already have left ``pending`` but not yet claimed dispatch; the
            # store then cancels its still-queued record atomically instead of
            # leaving queued+cancel-requested without a queue entry.
            updated = store.cancel_queued_or_mark_requested(project_root, request_id)
            if updated["state"] == "cancelled":
                logger.info("gateway request cancelled before running", extra={"request-id": request_id})
            elif is_running:
                # Persisted so the intent is observable (get/wait) and so the
                # dispatch retry/fallback loop can see it across process/module
                # boundaries — the in-memory cancel_requested set alone is not
                # enough once the record is inspected from outside this manager.
                logger.info("gateway request cancel-requested (running)", extra={"request-id": request_id})
                # RV680: a running SESSION turn is interruptible via the ACP
                # protocol-level cancel — signal it best-effort. Non-session
                # requests keep the between-attempts cooperative check only.
                try:
                    from audiagentic.components.agents.agents_gateway_sessions import (
                        peek_session_runtime,
                    )

                    runtime = peek_session_runtime()
                    if runtime is not None:
                        runtime.request_cancel(request_id)
                except Exception:  # noqa: BLE001 — cancel stays best-effort
                    logger.debug(
                        "failed to signal session turn cancel",
                        extra={"request-id": request_id},
                        exc_info=True,
                    )
            return updated
        return store.read_record(project_root, request_id)

    def wait(self, project_root: Path, request_id: str, timeout_seconds: float | None) -> dict[str, Any]:
        """Block until the request reaches a terminal state or timeout elapses.

        The durable record remains the authority, so this also works when a
        different manager or process owns dispatch.  To avoid JSON parsing and
        schema validation every 50ms for unchanged long-running requests, use
        the record file's change marker as a hint and retain a bounded full
        read fallback for coarse or unreliable filesystem timestamps.
        """
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        record_path = gateway_request_path(project_root, request_id)
        backoff_seconds = _WAIT_INITIAL_BACKOFF_SECONDS
        record = store.read_record(project_root, request_id)
        signature = _record_signature(record_path)
        next_full_read_at = time.monotonic() + _WAIT_MAX_BACKOFF_SECONDS

        while True:
            if record["state"] in store.TERMINAL_STATES:
                return record
            now = time.monotonic()
            if deadline is not None and now >= deadline:
                return record

            sleep_seconds = backoff_seconds
            if deadline is not None:
                sleep_seconds = min(sleep_seconds, max(0.0, deadline - now))
            time.sleep(sleep_seconds)

            now = time.monotonic()
            observed_signature = _record_signature(record_path)
            marker_changed = observed_signature != signature
            fallback_due = now >= next_full_read_at
            if marker_changed or fallback_due:
                record = store.read_record(project_root, request_id)
                signature = _record_signature(record_path)
                next_full_read_at = now + _WAIT_MAX_BACKOFF_SECONDS
                # A durable transition deserves prompt observation; reset the
                # bounded wait cadence rather than carrying a long idle delay.
                backoff_seconds = _WAIT_INITIAL_BACKOFF_SECONDS
            else:
                backoff_seconds = min(backoff_seconds * 2, _WAIT_MAX_BACKOFF_SECONDS)

    def queue_depth(self, agent_profile_id: str) -> dict[str, int]:
        """Return aggregate queue depth across all lanes for this profile.

        SH07 C2: multiple lanes (generations/digests) can exist for the same
        profile id; aggregate across them so the caller sees total capacity.
        """
        pending = 0
        running = 0
        active_running = 0
        idle = 0
        max_concurrency = 0

        with self._manager_lock:
            for lane_key_tuple, pq in self._lanes.items():
                if lane_key_tuple[0] == agent_profile_id:
                    with pq.lock:
                        pending += len(pq.pending)
                        running += len(pq.running)
                        active_running += pq.active_running()
                        idle += len(pq.idle)
                    max_concurrency += pq.max_concurrency

        return {
            "pending": pending,
            "running": running,
            "active_running": active_running,
            "idle": idle,
            "max_concurrency": max_concurrency,
        }

    def request_slot_status(self, agent_profile_id: str, request_id: str) -> str | None:
        pq = self._find_lane_for_request(agent_profile_id, request_id)
        if pq is None:
            return None
        with pq.lock:
            if request_id in pq.running:
                return "idle" if request_id in pq.idle else "active"
            for e in pq.pending:
                if e.request_id == request_id:
                    return "pending"
        return None

    def all_queue_depths(self) -> dict[str, dict[str, int]]:
        """Return queue depth keyed by redacted lane public id (no paths/secrets).

        SH07 C2: lanes are identified by their public lane key, not bare profile
        ids. Multiple projects sharing a lane see one entry for that lane.
        """
        with self._manager_lock:
            items = list(self._lanes.items())

        result: dict[str, dict[str, int]] = {}
        for lane_key_tuple, pq in items:
            lane_key = profiles_mod.GatewayExecutionLaneKey(*lane_key_tuple)
            public_id = lane_key.public_id()
            with pq.lock:
                result[public_id] = {
                    "pending": len(pq.pending),
                    "running": len(pq.running),
                    "active_running": pq.active_running(),
                    "idle": len(pq.idle),
                    "max_concurrency": pq.max_concurrency,
                }
        return result

    def _snapshot_all(self) -> dict[str, dict[str, int]]:
        """Immutable cross-lane snapshot of all queue depths.

        Acquires every lane lock simultaneously so the returned dict is a
        consistent view: running >= idle and active_running == running - idle
        hold for each lane *and* across lanes at the same instant.
        Lock ordering (sorted by lane key tuple) avoids deadlock with _drain.
        """
        with self._manager_lock:
            lane_key_tuples = sorted(self._lanes)
        pqs = [self._lanes[lkt] for lkt in lane_key_tuples]
        for pq in pqs:
            pq.lock.acquire()
        try:
            return {
                profiles_mod.GatewayExecutionLaneKey(*lkt).public_id(): {
                    "pending": len(pq.pending),
                    "running": len(pq.running),
                    "active_running": pq.active_running(),
                    "idle": len(pq.idle),
                    "max_concurrency": pq.max_concurrency,
                }
                for lkt, pq in zip(lane_key_tuples, pqs)
            }
        finally:
            for pq in reversed(pqs):
                pq.lock.release()
