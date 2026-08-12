"""Agent Execution Gateway scheduler and source-capacity manager.

In-process only — a worker thread pool with source reservations. Persisted
request state (agents_gateway_store) is
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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import gateway_request_path
from audiagentic.components.agents.gateway import profiles as profiles_mod
from audiagentic.components.agents.gateway import store as store
from audiagentic.components.agents.gateway.event_topics import (
    EXECUTION_CANCELLED_TOPIC,
    EXECUTION_COMPLETED_TOPIC,
    EXECUTION_FAILED_TOPIC,
    EXECUTION_INTERRUPTED_TOPIC,
    EXECUTION_QUEUED_TOPIC,
    EXECUTION_REJECTED_TOPIC,
    EXECUTION_STARTED_TOPIC,
)
from audiagentic.components.agents.gateway.instances import InstanceFacts
from audiagentic.components.agents.gateway.queue.capacity import (
    CapacityReservation,
    SourceCapacityAuthority,
)
from audiagentic.components.agents.gateway.queue.compat import (
    resolve_max_concurrency,
    resolve_queue_max_size,
)
from audiagentic.components.agents.gateway.queue.pending import PendingAuthority
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)


_WAIT_INITIAL_BACKOFF_SECONDS = 0.05
_WAIT_MAX_BACKOFF_SECONDS = 0.5

# SH07 crash-matrix test-only hook: widens the claim-to-start control-plane
# window so a real OS process kill can be observed landing inside it (the
# window is otherwise two adjacent synchronous store calls with no I/O
# between them — far too narrow to hit reliably from outside the process).
# No-op unless explicitly set; reading an unset env var costs nothing and
# changes no production behavior. See gateway_docker_harness.py callers.
_ENV_TEST_STALL_CLAIM_TO_START_MS = "AUDIAGENTIC_GATEWAY_TEST_STALL_CLAIM_TO_START_MS"


def _test_stall_claim_to_start() -> None:
    import os

    raw = os.environ.get(_ENV_TEST_STALL_CLAIM_TO_START_MS)
    if not raw:
        return
    try:
        ms = int(raw)
    except ValueError:
        return
    if ms > 0:
        time.sleep(ms / 1000.0)


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
    "queued": EXECUTION_QUEUED_TOPIC,
    "started": EXECUTION_STARTED_TOPIC,
    "completed": EXECUTION_COMPLETED_TOPIC,
    "failed": EXECUTION_FAILED_TOPIC,
    "cancelled": EXECUTION_CANCELLED_TOPIC,
    "rejected": EXECUTION_REJECTED_TOPIC,
    "interrupted": EXECUTION_INTERRUPTED_TOPIC,
}


def _publish_lifecycle_event(event_suffix: str, record: dict[str, Any]) -> None:
    """Publish an agents.execution.<event_suffix> lifecycle event for any gateway
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
        "execution-profile-id": record["execution-profile-id"],
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
            "failed to publish gateway lifecycle event",
            extra={"request-id": record["request-id"], "event": event_suffix},
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

    SH07 C2: snapshot provides gateway-owned execution identity; params
    comes from the resolved snapshot, not the caller.

    AS105/AS101: instance_facts is resolved once at enqueue time (not
    re-derived at dispatch) so binding decisions never race a mid-flight
    model-sources.yaml edit; project_key is the fairness grouping key for
    per-project round-robin selection among pending entries.
    """

    request_id: str
    project_root: Path
    execution_profile_id: str
    snapshot: profiles_mod.ResolvedExecutionProfile
    instance_facts: tuple[InstanceFacts, ...]
    project_key: str
    runner: RequestRunner
    owner_epoch: str
    service_root: Path | None


def _lane_public_id(lane_key_tuple: tuple[str, str, str]) -> str:
    """Human-readable lane identifier with no project paths or secrets.

    AS105/AS101: replaces the retired GatewayExecutionLaneKey.public_id() --
    the tuple itself (profile_id, generation, config_digest) is still the
    lane identity; only the class wrapper (and its lane_key()-as-capacity-key
    role) is retired.
    """
    profile_id, generation, config_digest = lane_key_tuple
    short_digest = config_digest.replace("sha256:", "")[:12]
    return f"{profile_id}/{generation}/{short_digest}"


# AS105/AS101 drain-before-swap: once a request for a different source
# sharing a gated resource has waited this long, stop admitting more of the
# currently-active source so in_flight can drain to zero and the resource
# can swap. Bounded anti-starvation guard, not a general scheduler.
_STARVATION_THRESHOLD_SECONDS = 30.0


class _RuntimeState:
    """Bookkeeping for one execution profile's active requests.

    Session-aware concurrency (AS15): pq.running tracks all dispatched requests,
    but pq.idle tracks those that are waiting on a session turn_lock (not doing
    real compute). The concurrency gate uses active_running = running - idle so
    idle sessions don't block other profiles from making progress.
    """

    def __init__(self, max_concurrency: int, queue_max_size: int) -> None:
        # Compatibility-only virtual capacity for undeclared sources.
        self._virtual_capacity = max_concurrency
        self._pending_limit = queue_max_size
        self.lock = threading.Lock()
        self.running: set[str] = set()
        self.idle: set[str] = set()
        self.cancel_requested: set[str] = set()

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
        self._runtime: dict[tuple[str, str, str], _RuntimeState] = {}
        self._manager_lock = threading.Lock()
        # AS105/AS101: shared machine-wide capacity per model-sources.yaml
        # resource-id -- deliberately NOT per-lane. A resource is genuinely
        # shared across every profile/project naming a source on it.
        self._capacity = SourceCapacityAuthority(
            starvation_seconds=_STARVATION_THRESHOLD_SECONDS,
        )
        # AS101: one canonical pending authority. Lanes retain only running
        # session/compatibility state; they no longer own pending work.
        self._pending_authority: PendingAuthority[QueuedDispatch] = PendingAuthority()
        self._active_requests: dict[str, tuple[Path, str]] = {}

    def _runtime_state(self, snapshot: profiles_mod.ResolvedExecutionProfile) -> _RuntimeState:
        lane_key_tuple = (snapshot.profile_id, snapshot.generation, snapshot.config_digest)
        with self._manager_lock:
            pq = self._runtime.get(lane_key_tuple)
            if pq is None:
                # AS105/AS101: these size the ungated (legacy semaphore) path
                # and the admission queue-depth backpressure limit for both
                # modes. Gated profiles ignore max_concurrency for compute
                # gating -- capacity comes from the resource trackers instead.
                params = dict(snapshot.execution_params)
                max_concurrency = resolve_max_concurrency(params)
                queue_max_size = resolve_queue_max_size(params, max_concurrency)
                pq = _RuntimeState(max_concurrency, queue_max_size)
                self._runtime[lane_key_tuple] = pq
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
        execution_profile_id = record["execution-profile-id"]

        # SH07 C2: reconstruct snapshot from record's admission-time identity.
        # The record was built with snapshot fields by submit_execution_request;
        # using them here prevents any project-local params override.
        snapshot = profiles_mod.snapshot_from_record(record)
        if snapshot is None:
            # Embedded mode (no shared-gateway registry persists gateway-
            # profile-id) or a pre-SH07-C2 test record: derive from the
            # record's own admission-time resolution, which store.build_record
            # always populates regardless of embedded/shared mode.
            resolved_provider_id = (
                record.get("resolved-provider-id")
                or params.get("provider_id")
                or params.get("provider-id", "")
            )
            # A record with no resolved-instance-ids at all (not even an
            # empty list -- e.g. a test harness or other direct caller that
            # builds a record without going through real admission) has no
            # instance identity to recover. Fall back to the profile id
            # itself as a single synthetic, always-ungated instance rather
            # than rejecting -- ResolvedExecutionProfile requires a
            # non-empty instances set structurally (AS105/AS101).
            resolved_instance_ids = record.get("resolved-instance-ids") or [execution_profile_id]
            snapshot = profiles_mod.snapshot_from_resolved_profile(
                profile_id=execution_profile_id,
                provider_id=resolved_provider_id,
                instances=tuple(resolved_instance_ids),
                params=params,
            )
        lane_label = f"{snapshot.profile_id}/{snapshot.generation}"

        # SH07 C2: validate snapshot is current before admission.
        # A stale snapshot means the gateway profile changed; reject with
        # CON-AGW-101 resubmit-required. The default AlwaysCurrentValidator
        # preserves existing behavior; tests inject a validator to simulate
        # generation changes.
        validator = profiles_mod.get_snapshot_validator()
        if not validator.validate_snapshot_current(snapshot):
            logger.info(
                "gateway request rejected: stale profile snapshot",
                extra={
                    "request-id": request_id,
                    "execution-profile-id": execution_profile_id,
                    "lane": lane_label,
                },
            )
            rejected = store.transition_record(
                project_root,
                request_id,
                "rejected",
                updates={
                    "error": {
                        "code": "CON-AGW-101",
                        "message": "gateway profile changed; resubmit required",
                        "kind": "agents",
                    }
                },
            )
            store.record_gateway_timeline(
                project_root,
                request_id,
                "queue.rejected-stale-snapshot",
                state=rejected["state"],
                attributes={
                    "execution-profile-id": execution_profile_id,
                    "lane": lane_label,
                    "gateway-profile-generation": snapshot.generation,
                    "correlation_id": (rejected.get("metadata") or {}).get("correlation_id"),
                },
            )
            _publish_lifecycle_event("rejected", rejected)
            return rejected

        owner_epoch = dispatch_owner_epoch or f"local-{uuid.uuid4().hex}"
        pq = self._runtime_state(snapshot)

        # AS105/AS101: resolve instance capacity facts once, at admission --
        # never re-derived at dispatch time, so a mid-flight model-sources.yaml
        # edit cannot change what a request already queued is bound against.
        from audiagentic.components.agents.gateway.instances import resolve_instance_facts

        instance_facts = resolve_instance_facts(project_root, snapshot.instances)
        # Lifecycle event publish is SYNC dispatch — a subscriber that calls
        # back into cancel()/enqueue() for the same profile would try to
        # re-acquire pq.lock and deadlock (threading.Lock is not reentrant).
        # Keep the critical section limited to the bounded admission check
        # itself; do all I/O and event publish after releasing the lock (RV31).
        entry = QueuedDispatch(
            request_id=request_id,
            project_root=project_root,
            execution_profile_id=execution_profile_id,
            snapshot=snapshot,
            instance_facts=instance_facts,
            project_key=str(project_root),
            runner=runner,
            owner_epoch=owner_epoch,
            service_root=dispatch_service_root,
        )
        pending_count = 0
        with pq.lock:
            queue_full = self._pending_authority.count(
                lambda request: request.value.snapshot == snapshot
            ) >= pq._pending_limit
            if not queue_full:
                self._pending_authority.enqueue(
                    request_id=entry.request_id,
                    project_key=entry.project_key,
                    value=entry,
                )
                pending_count = self._pending_authority.count(
                    lambda request: request.value.snapshot == snapshot
                )

        if queue_full:
            logger.info(
                "gateway request rejected: queue full",
                extra={
                    "request-id": request_id,
                    "execution-profile-id": execution_profile_id,
                    "queue-max-size": pq._pending_limit,
                },
            )
            rejected = store.transition_record(
                project_root,
                request_id,
                "rejected",
                updates={
                    "error": {
                        "code": "VAL-AGW-025",
                        "message": f"queue full (legacy pending limit) for profile {execution_profile_id!r} (max {pq._pending_limit})",
                        "kind": "agents",
                    }
                },
            )
            store.record_gateway_timeline(
                project_root,
                request_id,
                "queue.rejected",
                state=rejected["state"],
                attributes={
                    "execution-profile-id": execution_profile_id,
                    "queue-max-size": pq._pending_limit,
                    "correlation_id": (rejected.get("metadata") or {}).get("correlation_id"),
                },
            )
            _publish_lifecycle_event("rejected", rejected)
            return rejected

        logger.info(
            "gateway request queued",
            extra={
                "request-id": request_id,
                "execution-profile-id": execution_profile_id,
                "pending": pending_count,
            },
        )
        store.record_gateway_timeline(
            project_root,
            request_id,
            "queue.queued",
            state=record["state"],
            attributes={
                "execution-profile-id": execution_profile_id,
                "pending": pending_count,
                "correlation_id": (record.get("metadata") or {}).get("correlation_id"),
            },
        )
        _publish_lifecycle_event("queued", record)

        self._drain_all()
        return store.read_record(project_root, request_id)

    def _drain_all(self) -> None:
        """Claim fair project heads and start any currently eligible work.

        Capacity is checked before a pending request is removed.  The pending
        authority rotates only the project that actually starts work, so an
        unavailable project head cannot starve another project with capacity.
        """
        while True:
            started = False
            for candidate in self._pending_authority.candidates():
                entry = candidate.value
                pq = self._runtime_state(entry.snapshot)
                reservation: CapacityReservation | None = None
                with pq.lock:
                    reservation = self._try_reserve_source(entry, pq._virtual_capacity)
                    if reservation is None:
                        continue
                    claimed = self._pending_authority.claim(entry.request_id)
                    if claimed is None:
                        if reservation is not None:
                            self._capacity.release(reservation)
                        continue
                    pq.running.add(entry.request_id)
                    self._active_requests[entry.request_id] = (
                        entry.project_root, entry.execution_profile_id,
                    )
                thread = threading.Thread(
                    target=self._run_one,
                    args=(pq, entry, reservation),
                    daemon=True,
                    name=f"gateway-{entry.execution_profile_id}-{entry.request_id}",
                )
                thread.start()
                started = True
                break
            if not started:
                return

    def _try_reserve_source(
        self, entry: QueuedDispatch, fallback_concurrency: int,
    ) -> CapacityReservation | None:
        """Reserve one compatible instance through the common capacity model.

        Declared model sources use their shared physical resource.  Plain
        instances use a profile-scoped virtual resource only to preserve the
        existing profile limit while removing the separate semaphore path.
        """
        virtual_resource = (
            f"profile:{entry.snapshot.profile_id}/"
            f"{entry.snapshot.generation}/{entry.snapshot.config_digest}"
        )
        for facts in entry.instance_facts:
            declared = facts.resource_id is not None
            reservation = self._capacity.try_reserve(
                source_id=facts.source_id,
                resource_id=facts.resource_id if declared else virtual_resource,
                concurrency=facts.concurrency if declared else fallback_concurrency,
                model_id=facts.model_id,
                capacity_source_id=facts.source_id if declared else virtual_resource,
                declared=declared,
            )
            if reservation is not None:
                return reservation
        return None

    def _run_one(
        self,
        pq: _RuntimeState,
        entry: QueuedDispatch,
        bound: CapacityReservation | None,
    ) -> None:
        project_root = entry.project_root
        execution_profile_id = entry.execution_profile_id
        request_id = entry.request_id
        owner_epoch = entry.owner_epoch
        runner = entry.runner
        service_root = entry.service_root
        lane_label = f"{entry.snapshot.profile_id}/{entry.snapshot.generation}"

        is_session = False
        try:
            if request_id in pq.cancel_requested:
                logger.info(
                    "gateway request cancelled before dispatch", extra={"request-id": request_id}
                )
                cancelled = store.cancel_queued_or_mark_requested(project_root, request_id)
                if cancelled["state"] == "cancelled":
                    store.record_gateway_timeline(
                        project_root,
                        request_id,
                        "queue.cancelled-before-dispatch",
                        state="cancelled",
                    )
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
                    extra={"request-id": request_id, "lane": lane_label},
                )
                rejected = store.transition_record(
                    project_root,
                    request_id,
                    "rejected",
                    updates={
                        "error": {
                            "code": "CON-AGW-101",
                            "message": "gateway profile changed; resubmit required",
                            "kind": "agents",
                        }
                    },
                )
                store.record_gateway_timeline(
                    project_root,
                    request_id,
                    "queue.rejected-stale-dispatch",
                    state=rejected["state"],
                    attributes={
                        "execution-profile-id": execution_profile_id,
                        "lane": lane_label,
                        "gateway-profile-generation": entry.snapshot.generation,
                    },
                )
                _publish_lifecycle_event("rejected", rejected)
                return

            current = store.read_record(project_root, request_id)
            try:
                claimed = store.claim_dispatch(
                    project_root,
                    request_id,
                    owner_epoch=owner_epoch,
                    expected_revision=current["revision"],
                    service_root=service_root,
                )
            except AudiaGenticError as exc:  # noqa: SIM102
                # Cancellation may linearize after this worker has dequeued the
                # request but before its durable claim is written.  That makes
                # this claim deliberately stale: the cancellation is already
                # the authoritative terminal outcome, so this worker only has
                # cleanup left to do.  Keep every other claim conflict loud --
                # it is evidence of an ownership/revision bug, not a retry
                # opportunity.
                latest = store.read_record(project_root, request_id)
                if exc.code in {"CON-AGW-071", "CON-AGW-083"} and latest["state"] == "cancelled":
                    logger.info(
                        "gateway dispatch claim superseded by durable cancellation",
                        extra={"request-id": request_id},
                    )
                    _publish_lifecycle_event("cancelled", latest)
                    return
                raise
            if claimed["state"] != "queued":
                return
            _test_stall_claim_to_start()
            worker_id = f"worker_{uuid.uuid4().hex[:16]}"
            if bound is not None:
                # A capacity reservation is not enough: persist the exact
                # source/model under the same owner/revision fence that starts
                # execution, before the provider runner can observe it. Plain
                # instances use their source id as the durable model identity;
                # this keeps bounded and unbounded placement on one contract.
                record = store.bind_and_start_owned_attempt(
                    project_root,
                    request_id,
                    owner_epoch=owner_epoch,
                    worker_id=worker_id,
                    expected_revision=claimed["revision"],
                    resolved_source_id=bound.source_id,
                    resolved_model_id=bound.model_id or bound.source_id,
                    resolved_capacity_generation=bound.capacity_source_id,
                )
            else:
                record = store.start_owned_attempt(
                    project_root,
                    request_id,
                    owner_epoch=owner_epoch,
                    worker_id=worker_id,
                    expected_revision=claimed["revision"],
                )
            logger.info(
                "gateway request running",
                extra={"request-id": request_id, "execution-profile-id": execution_profile_id},
            )
            store.record_gateway_timeline(
                project_root,
                request_id,
                "queue.started",
                state=record["state"],
                attributes={
                    "execution-profile-id": execution_profile_id,
                    "correlation_id": (record.get("metadata") or {}).get("correlation_id"),
                },
            )
            _publish_lifecycle_event("started", record)

            # AS15: two-phase concurrency for session requests.
            # Detect session request early to set up callbacks.
            is_session = bool(record.get("session-id") or record.get("session-keep-alive"))
            if is_session:
                # Admission only proves the session can start. Capacity is
                # held by the request-specific callbacks around actual turns,
                # never across an idle keep-alive lifetime.
                turn_template = bound
                if bound is not None:
                    self._capacity.release(bound)
                    bound = None
                with pq.lock:
                    pq.idle.add(request_id)

                turn_reservation: CapacityReservation | None = None

                async def _on_turn_starting(rid: str) -> None:
                    nonlocal turn_reservation
                    if turn_template is None:
                        raise RuntimeError("session turn has no capacity reservation template")
                    turn_reservation = await asyncio.to_thread(
                        self._capacity.reserve_when_available, turn_template,
                    )
                    with pq.lock:
                        pq.idle.discard(rid)

                async def _on_turn_done(rid: str) -> None:
                    nonlocal turn_reservation
                    with pq.lock:
                        released = turn_reservation
                        turn_reservation = None
                        pq.idle.add(rid)
                    if released is not None:
                        self._capacity.release(released)
                    self._drain_all()

                _TURNCB.set_callbacks(request_id, _on_turn_starting, _on_turn_done)
                # This worker is waiting at the session/turn boundary, so let
                # another request reach the same bounded compute gate.
                self._drain_all()
            # Every non-session dispatch has a source reservation from the
            # common capacity authority; there is no ungated semaphore path.

            try:
                result = runner(project_root, record)
                logger.info(
                    "gateway request finished",
                    extra={
                        "request-id": request_id,
                        "state": result.get("state") if isinstance(result, dict) else None,
                    },
                )
                if isinstance(result, dict):
                    store.record_gateway_timeline(
                        project_root,
                        request_id,
                        "queue.finished",
                        state=result.get("state"),
                        attributes={
                            "execution-profile-id": execution_profile_id,
                            "correlation_id": (result.get("metadata") or {}).get("correlation_id"),
                        },
                    )
                if isinstance(result, dict) and result.get("state") in (
                    "completed",
                    "failed",
                    "cancelled",
                ):
                    _publish_lifecycle_event(result["state"], result)
            except AudiaGenticError as exc:
                logger.error(
                    "gateway request runner raised", extra={"request-id": request_id}, exc_info=True
                )
                current = store.read_record(project_root, request_id)
                if current["state"] == "running":
                    failed = store.transition_owned_terminal(
                        project_root,
                        request_id,
                        "failed",
                        updates={"error": exc, "finished-at": now_iso_z()},
                        owner_epoch=record["dispatch-owner-epoch"],
                        worker_id=record["worker-id"],
                        attempt_epoch=record["attempt-epoch"],
                    )
                    _publish_lifecycle_event("failed", failed)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "gateway request runner raised unexpectedly",
                    extra={"request-id": request_id},
                    exc_info=True,
                )
                current = store.read_record(project_root, request_id)
                if current["state"] == "running":
                    failed = store.transition_owned_terminal(
                        project_root,
                        request_id,
                        "failed",
                        updates={"error": exc, "finished-at": now_iso_z()},
                        owner_epoch=record["dispatch-owner-epoch"],
                        worker_id=record["worker-id"],
                        attempt_epoch=record["attempt-epoch"],
                    )
                    _publish_lifecycle_event("failed", failed)
        finally:
            if bound is not None:
                self._capacity.release(bound)
            with pq.lock:
                pq.running.discard(request_id)
                pq.idle.discard(request_id)
                pq.cancel_requested.discard(request_id)
            self._active_requests.pop(request_id, None)
            _TURNCB.clear(request_id)
            self._drain_all()

    def _find_lane_for_request(
        self, execution_profile_id: str, request_id: str
    ) -> _RuntimeState | None:
        """Scan lanes to find the queue that contains or tracks this request.

        Backward-compat: caller only knows execution_profile_id, not the full lane key.
        """
        with self._manager_lock:
            for lane_key_tuple, pq in self._runtime.items():
                if lane_key_tuple[0] == execution_profile_id:
                    # Profile matches; check if this request is tracked here
                    with pq.lock:
                        if request_id in pq.running:
                            return pq
        return None

    def cancel(self, project_root: Path, execution_profile_id: str, request_id: str) -> dict[str, Any]:
        """Cancel a queued request, or mark a running one cancel-requested (best-effort).

        A request that is already running is NOT force-transitioned to
        'cancelled' — the runner may complete normally. Callers should not
        assume the terminal state will be 'cancelled' for a cancel issued
        against a running request (RV15 finding).
        """
        removed = self._pending_authority.remove(request_id)
        if removed is not None:
            return store.cancel_queued_or_mark_requested(project_root, request_id)

        pq = self._find_lane_for_request(execution_profile_id, request_id)
        if pq is None:
            # A remote service/process can own the in-memory queue.  Durable
            # cancellation still has to reach the record even when this local
            # manager has no profile queue.
            return store.cancel_queued_or_mark_requested(project_root, request_id)

        with pq.lock:
            removed_from_queue = False
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
                logger.info(
                    "gateway request cancelled before running", extra={"request-id": request_id}
                )
            elif is_running:
                # Persisted so the intent is observable (get/wait) and so the
                # dispatch retry/fallback loop can see it across process/module
                # boundaries — the in-memory cancel_requested set alone is not
                # enough once the record is inspected from outside this manager.
                logger.info(
                    "gateway request cancel-requested (running)", extra={"request-id": request_id}
                )
                # RV680: a running SESSION turn is interruptible via the ACP
                # protocol-level cancel — signal it best-effort. Non-session
                # requests keep the between-attempts cooperative check only.
                try:
                    from audiagentic.components.agents.gateway.session.sessions import (
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

    def wait(
        self, project_root: Path, request_id: str, timeout_seconds: float | None
    ) -> dict[str, Any]:
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
            # Local pending work can wake this waiter as soon as admission,
            # cancellation or dispatch changes the pending authority.  Once
            # dispatch has claimed it (or another host owns it), retain the
            # durable-record polling path below as the cross-process truth.
            if self._pending_authority.contains(request_id):
                self._pending_authority.wait_for_change(sleep_seconds)
            else:
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

    def queue_depth(self, execution_profile_id: str) -> dict[str, int]:
        """Return aggregate queue depth across all lanes for this profile.

        SH07 C2: multiple lanes (generations/digests) can exist for the same
        profile id; aggregate across them so the caller sees total capacity.
        """
        pending = self._pending_authority.count(
            lambda request: request.value.execution_profile_id == execution_profile_id
        )
        running = 0
        active_running = 0
        idle = 0
        max_concurrency = 0

        with self._manager_lock:
            for lane_key_tuple, pq in self._runtime.items():
                if lane_key_tuple[0] == execution_profile_id:
                    with pq.lock:
                        running += len(pq.running)
                        active_running += pq.active_running()
                        idle += len(pq.idle)
                    max_concurrency += pq._virtual_capacity

        return {
            "pending": pending,
            "running": running,
            "active_running": active_running,
            "idle": idle,
            "max_concurrency": max_concurrency,
        }

    def request_slot_status(self, execution_profile_id: str, request_id: str) -> str | None:
        pending = self._pending_authority.get(request_id)
        if pending is not None and pending.value.execution_profile_id == execution_profile_id:
            return "pending"
        pq = self._find_lane_for_request(execution_profile_id, request_id)
        if pq is None:
            return None
        with pq.lock:
            if request_id in pq.running:
                return "idle" if request_id in pq.idle else "active"
        return None

    def source_capacity_status(self) -> dict[str, dict[str, Any]]:
        """Return redacted source-capacity state for operator diagnostics."""
        return self._capacity.snapshots()

    def all_queue_depths(self) -> dict[str, dict[str, int]]:
        """Deprecated compatibility projection; use project/source status."""
        """Return queue depth keyed by redacted lane public id (no paths/secrets).

        SH07 C2: lanes are identified by their public lane key, not bare profile
        ids. Multiple projects sharing a lane see one entry for that lane.
        """
        with self._manager_lock:
            items = list(self._runtime.items())

        result: dict[str, dict[str, int]] = {}
        for lane_key_tuple, pq in items:
            public_id = _lane_public_id(lane_key_tuple)
            with pq.lock:
                result[public_id] = {
                    "pending": self._pending_authority.count(
                        lambda request, lane=lane_key_tuple: (
                            request.value.snapshot.profile_id,
                            request.value.snapshot.generation,
                            request.value.snapshot.config_digest,
                        ) == lane
                    ),
                    "running": len(pq.running),
                    "active_running": pq.active_running(),
                    "idle": len(pq.idle),
                    "max_concurrency": pq._virtual_capacity,
                }
        return result

    def project_queue_depths(self, project_root: Path) -> dict[str, dict[str, int]]:
        """Return redacted queue depth grouped by execution profile for a project.

        This is the operator-facing reporting authority. It deliberately does
        not expose internal lane keys or other projects' work.
        """
        project_key = str(project_root)
        result: dict[str, dict[str, int]] = {}
        pending_by_profile = self._pending_authority.count_by(
            lambda request: (
                request.project_key,
                request.value.execution_profile_id,
            )
        )
        for (request_project, profile_id), count in pending_by_profile.items():
            if request_project != project_key:
                continue
            result[profile_id] = {
                "pending": count, "running": 0, "active_running": 0, "idle": 0,
            }
        with self._manager_lock:
            active = [
                (request_id, profile_id)
                for request_id, (root, profile_id) in self._active_requests.items()
                if root == project_root
            ]
        for request_id, profile_id in active:
            depth = result.setdefault(profile_id, {
                "pending": 0, "running": 0, "active_running": 0, "idle": 0,
            })
            depth["running"] += 1
            status = self.request_slot_status(profile_id, request_id)
            if status == "idle":
                depth["idle"] += 1
            else:
                depth["active_running"] += 1
        return result

    def _snapshot_all(self) -> dict[str, dict[str, int]]:
        """Immutable cross-lane snapshot of all queue depths.

        Acquires every lane lock simultaneously so the returned dict is a
        consistent view: running >= idle and active_running == running - idle
        hold for each lane *and* across lanes at the same instant.
        Lock ordering (sorted by lane key tuple) avoids deadlock with _drain.
        """
        with self._manager_lock:
            lane_key_tuples = sorted(self._runtime)
        pqs = [self._runtime[lkt] for lkt in lane_key_tuples]
        for pq in pqs:
            pq.lock.acquire()
        try:
            return {
                _lane_public_id(lkt): {
                    "pending": self._pending_authority.count(
                        lambda request, lane=lkt: (
                            request.value.snapshot.profile_id,
                            request.value.snapshot.generation,
                            request.value.snapshot.config_digest,
                        ) == lane
                    ),
                    "running": len(pq.running),
                    "active_running": pq.active_running(),
                    "idle": len(pq.idle),
                    "max_concurrency": pq._virtual_capacity,
                }
                for lkt, pq in zip(lane_key_tuples, pqs)
            }
        finally:
            for pq in reversed(pqs):
                pq.lock.release()
