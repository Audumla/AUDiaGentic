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
    OverlayReservation,
    ScopedCapacityAuthority,
    SourceCapacityAuthority,
)
from audiagentic.components.agents.gateway.queue.capacity_policy import (
    resolve_capacity_limits,
    resolve_pending_capacity,
)
from audiagentic.components.agents.gateway.queue.pending import PendingAuthority
from audiagentic.components.agents.gateway.queue.watchdog_registry import watchdog_registry
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
    stored in a thread-safe dict to support virtual_capacity > 1 (AS15).

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
        # A runner may append the authoritative provider/model identity to
        # the attempt before the terminal request snapshot is refreshed. Use
        # that attempt as a fallback so observers never lose attribution due
        # to the persistence ordering of the two records.
        attempts = record.get("attempts") or []
        latest_attempt = attempts[-1] if attempts else {}
        payload["provider-id"] = record.get("provider-id") or latest_attempt.get("provider-id")
        payload["model-id"] = record.get("model-id") or latest_attempt.get("model-id")
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
class _QueueReservation:
    """Physical reservation plus optional gateway scope overlays."""

    source: CapacityReservation
    overlay: OverlayReservation | None

    @property
    def source_id(self) -> str:
        return self.source.source_id

    @property
    def model_id(self) -> str | None:
        return self.source.model_id

    @property
    def capacity_source_id(self) -> str:
        return self.source.capacity_source_id


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
    session_key: str | None
    runner: RequestRunner
    owner_epoch: str
    service_root: Path | None
    # A continuation inherits the immutable physical source selected when
    # the durable session was opened.  New sessions leave this unset until
    # their first dispatch publishes the binding.
    session_source_id: str | None = None


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

    def __init__(self, virtual_capacity: int | None, pending_capacity: int) -> None:
        # Provider-neutral fallback capacity for sources without declarations.
        self.virtual_capacity = virtual_capacity
        self.pending_capacity = pending_capacity
        self.lock = threading.Lock()
        self.running: set[str] = set()
        self.idle: set[str] = set()
        self.cancel_requested: set[str] = set()

    def active_running(self) -> int:
        """Count of requests actually consuming compute (not waiting on session locks)."""
        return len(self.running) - len(self.idle)


@dataclass(frozen=True)
class ProfileGenerationIdentity:
    """Immutable identity for one resolved execution-profile generation."""

    profile_id: str
    generation: str
    config_digest: str


class GatewayQueueManager:
    """Per-profile FIFO queues with strict concurrency, cancel, and wait.

    One manager instance is expected to live for the lifetime of the hosting
    process (module-level singleton in agents_gateway_api). Not safe to share
    across processes — see the module docstring's durability caveat.
    """

    def __init__(self) -> None:
        self._runtime: dict[ProfileGenerationIdentity, _RuntimeState] = {}
        self._manager_lock = threading.Lock()
        # AS105/AS101: shared machine-wide capacity per model-sources.yaml
        # resource-id -- deliberately NOT per-lane. A resource is genuinely
        # shared across every profile/project naming a source on it.
        self._capacity = SourceCapacityAuthority(
            starvation_seconds=_STARVATION_THRESHOLD_SECONDS,
        )
        self._scoped_capacity = ScopedCapacityAuthority()
        # AS101: one canonical pending authority. Lanes retain only running
        # session/compatibility state; they no longer own pending work.
        self._pending_authority: PendingAuthority[QueuedDispatch] = PendingAuthority()
        self._active_requests: dict[str, tuple[Path, str]] = {}

    def _runtime_state(self, snapshot: profiles_mod.ResolvedExecutionProfile) -> _RuntimeState:
        profile_identity = ProfileGenerationIdentity(
            snapshot.profile_id, snapshot.generation, snapshot.config_digest
        )
        with self._manager_lock:
            pq = self._runtime.get(profile_identity)
            if pq is None:
                # AS105/AS101: these size the ungated (legacy semaphore) path
                # and the admission queue-depth backpressure limit for both
                # modes. Gated profiles ignore virtual_capacity for compute
                # gating -- capacity comes from the resource trackers instead.
                params = dict(snapshot.execution_params)
                virtual_capacity = resolve_capacity_limits(params)["global"]
                pending_capacity = resolve_pending_capacity(params, virtual_capacity)
                pq = _RuntimeState(virtual_capacity, pending_capacity)
                self._runtime[profile_identity] = pq
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
                    "profile": lane_label,
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
                    "profile": lane_label,
                    "gateway-profile-generation": snapshot.generation,
                    "correlation_id": (rejected.get("metadata") or {}).get("correlation_id"),
                },
            )
            _publish_lifecycle_event("rejected", rejected)
            return rejected

        # Records persist the gateway snapshot identity (generation and
        # digest), not its execution parameters.  Recover the current,
        # validated gateway snapshot before sizing the runtime lane; using
        # snapshot_from_record()'s intentionally parameter-free shape would
        # silently fall back to capacity=1 and would also break queue-depth
        # accounting for non-default limits.
        shared_registry = profiles_mod.get_gateway_registry()
        if shared_registry is not None and profiles_mod.snapshot_from_record(record) is not None:
            snapshot = shared_registry.resolve_snapshot(snapshot.profile_id)

        owner_epoch = dispatch_owner_epoch or f"local-{uuid.uuid4().hex}"
        try:
            pq = self._runtime_state(snapshot)
        except AudiaGenticError as exc:
            # Capacity policy is part of admission. If a persisted request
            # reached this boundary before validation, never leave it stranded
            # as queued with no pending-authority entry.
            rejected = store.transition_record(
                project_root,
                request_id,
                "rejected",
                updates={"error": exc},
            )
            store.record_gateway_timeline(
                project_root,
                request_id,
                "queue.rejected-invalid-capacity",
                state=rejected["state"],
                attributes={"execution-profile-id": execution_profile_id},
            )
            _publish_lifecycle_event("rejected", rejected)
            return rejected

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
        session_source_id = self._durable_session_source_id(
            project_root, record.get("session-id")
        )
        entry = QueuedDispatch(
            request_id=request_id,
            project_root=project_root,
            execution_profile_id=execution_profile_id,
            snapshot=snapshot,
            instance_facts=instance_facts,
            # Resolve once so relative/symlinked callers cannot accidentally
            # bypass a per-project limit for the same physical project.
            project_key=str(project_root.resolve()),
            session_key=str(record.get("session-id")) if record.get("session-id") else None,
            runner=runner,
            owner_epoch=owner_epoch,
            service_root=dispatch_service_root,
            session_source_id=session_source_id,
        )
        pending_count = 0
        with pq.lock:
            queue_full = self._pending_authority.count(
                lambda request: (
                    request.value.snapshot.profile_id == snapshot.profile_id
                    and request.value.snapshot.generation == snapshot.generation
                    and request.value.snapshot.config_digest == snapshot.config_digest
                )
            ) >= pq.pending_capacity
            if not queue_full:
                self._pending_authority.enqueue(
                    request_id=entry.request_id,
                    project_key=entry.project_key,
                    value=entry,
                )
                pending_count = self._pending_authority.count(
                    lambda request: (
                        request.value.snapshot.profile_id == snapshot.profile_id
                        and request.value.snapshot.generation == snapshot.generation
                        and request.value.snapshot.config_digest == snapshot.config_digest
                    )
                )

        if queue_full:
            logger.info(
                "gateway request rejected: queue full",
                extra={
                    "request-id": request_id,
                    "execution-profile-id": execution_profile_id,
                    "pending-capacity": pq.pending_capacity,
                },
            )
            rejected = store.transition_record(
                project_root,
                request_id,
                "rejected",
                updates={
                    "error": {
                        "code": "VAL-AGW-025",
                        "message": f"queue full for profile {execution_profile_id!r} (max {pq.pending_capacity})",
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
                    "pending-capacity": pq.pending_capacity,
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
                reservation: _QueueReservation | None = None
                with pq.lock:
                    reservation = self._try_reserve_source(entry, pq)
                    if reservation is None:
                        continue
                    claimed = self._pending_authority.claim(entry.request_id)
                    if claimed is None:
                        if reservation is not None:
                            self._capacity.release(reservation.source)
                            self._scoped_capacity.release(reservation.overlay)
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
        self, entry: QueuedDispatch, pq: _RuntimeState,
    ) -> "_QueueReservation | None":
        """Reserve one compatible instance through the common capacity model.

        Declared model sources use their shared physical resource.  Plain
        instances use a profile-scoped virtual resource only to preserve the
        existing profile limit while removing the separate semaphore path.
        """
        limits, scope_keys = self._scope_keys(entry)
        # A source without a declaration uses the configured global overlay
        # as its fallback; None deliberately means unbounded.
        virtual_resource = (
            f"profile:{entry.snapshot.profile_id}/"
            f"{entry.snapshot.generation}/{entry.snapshot.config_digest}"
        )
        compatible_facts = (
            facts
            for facts in entry.instance_facts
            if entry.session_source_id is None or facts.source_id == entry.session_source_id
        )
        for facts in compatible_facts:
            declared = facts.resource_id is not None
            global_limit = limits["global"]
            virtual_bound = global_limit is not None
            overlay = self._scoped_capacity.try_reserve(tuple(scope_keys))
            if overlay is None:
                return None
            reservation = self._capacity.try_reserve(
                source_id=facts.source_id,
                resource_id=facts.resource_id if declared else (virtual_resource if virtual_bound else None),
                concurrency=facts.concurrency if declared else (int(global_limit) if global_limit is not None else None),
                model_id=facts.model_id,
                capacity_source_id=facts.source_id if declared else (virtual_resource if virtual_bound else facts.source_id),
                declared=declared,
            )
            if reservation is not None:
                return _QueueReservation(reservation, overlay)
            self._scoped_capacity.release(overlay)
        return None

    @staticmethod
    def _durable_session_source_id(project_root: Path, session_id: object) -> str | None:
        """Read the immutable source binding for a continuation, if present."""
        if not session_id:
            return None
        try:
            from audiagentic.components.agents.gateway.session import sessions_store

            record = sessions_store.read_session_record(project_root, str(session_id))
        except Exception:  # noqa: BLE001 - admission remains compatible with new sessions
            return None
        value = sessions_store.session_provider_metadata(record).get(
            "gateway-capacity-source-id"
        )
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _scope_keys(entry: QueuedDispatch) -> tuple[dict[str, int | None | bool], list[tuple[str, int]]]:
        limits = resolve_capacity_limits(dict(entry.snapshot.execution_params))
        keys: list[tuple[str, int]] = []
        # An explicitly configured global overlay applies to declared
        # physical sources as well as virtual sources. The legacy implicit
        # virtual-capacity default is intentionally left to the virtual
        # resource so declared model-source capacity remains unchanged.
        if bool(limits["global-explicit"]) and limits["global"] is not None:
            keys.append(("global", int(limits["global"])))
        if limits["project"] is not None:
            keys.append((f"project:{entry.project_key}", int(limits["project"])))
        if limits["session"] is not None and entry.session_key is not None:
            # Session IDs are only unique within a project root. Include the
            # canonical project key so imported/deterministic IDs in separate
            # projects do not contend for one another's turn budget.
            keys.append(
                (f"session:{entry.project_key}:{entry.session_key}", int(limits["session"]))
            )
        return limits, keys

    def _try_reserve_specific_source(
        self, entry: QueuedDispatch, pq: _RuntimeState, template: _QueueReservation,
    ) -> "_QueueReservation | None":
        """Reacquire the same source selected at session admission.

        A session's durable binding identifies the source chosen at admission;
        a later turn must not silently select a different instance merely
        because another compatible source is currently free.
        """
        _limits, scope_keys = self._scope_keys(entry)
        overlay = self._scoped_capacity.try_reserve(tuple(scope_keys))
        if overlay is None:
            return None
        source = template.source
        reservation = self._capacity.try_reserve(
            source_id=source.source_id,
            resource_id=source.resource_id,
            concurrency=source.concurrency,
            model_id=source.model_id,
            capacity_source_id=source.capacity_source_id,
            declared=source.declared,
        )
        if reservation is None:
            self._scoped_capacity.release(overlay)
            return None
        return _QueueReservation(reservation, overlay)

    def _release_reservation(self, reservation: "_QueueReservation") -> None:
        self._capacity.release(reservation.source)
        self._scoped_capacity.release(reservation.overlay)

    def _reserve_session_when_available(
        self, entry: QueuedDispatch, pq: _RuntimeState, template: _QueueReservation,
        cancelled: threading.Event | None = None,
    ) -> "_QueueReservation":
        """Acquire both physical and optional project/session overlays."""
        while True:
            if cancelled is not None and cancelled.is_set():
                raise asyncio.CancelledError
            with pq.lock:
                reservation = self._try_reserve_specific_source(entry, pq, template)
            if reservation is not None:
                if cancelled is not None and cancelled.is_set():
                    self._release_reservation(reservation)
                    raise asyncio.CancelledError
                return reservation
            time.sleep(0.1)

    def _run_one(
        self,
        pq: _RuntimeState,
        entry: QueuedDispatch,
        bound: _QueueReservation | None,
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
                    extra={"request-id": request_id, "profile": lane_label},
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
                        "profile": lane_label,
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
            watchdog_registry().register(project_root, record)
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
                    self._release_reservation(bound)
                    bound = None
                with pq.lock:
                    pq.idle.add(request_id)

                turn_reservation: _QueueReservation | None = None
                turn_acquire_cancel = threading.Event()

                async def _on_turn_starting(rid: str) -> None:
                    nonlocal turn_reservation
                    if turn_template is None:
                        raise RuntimeError("session turn has no capacity reservation template")
                    turn_acquire_cancel.clear()
                    try:
                        turn_reservation = await asyncio.to_thread(
                            self._reserve_session_when_available,
                            entry, pq, turn_template, turn_acquire_cancel,
                        )
                    except asyncio.CancelledError:
                        turn_acquire_cancel.set()
                        raise
                    with pq.lock:
                        pq.idle.discard(rid)

                async def _on_turn_done(rid: str) -> None:
                    nonlocal turn_reservation
                    with pq.lock:
                        released = turn_reservation
                        turn_reservation = None
                        pq.idle.add(rid)
                    if released is not None:
                        self._release_reservation(released)
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
                    # The runner may return an in-memory transition snapshot
                    # that predates a separately persisted attempt update.
                    # Re-read the terminal record before projecting the event
                    # so observers receive the durable provider/model and
                    # attempt attribution.
                    terminal_record = store.read_record(project_root, request_id)
                    _publish_lifecycle_event(terminal_record["state"], terminal_record)
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
            watchdog_registry().unregister(project_root, request_id)
            if bound is not None:
                self._release_reservation(bound)
            with pq.lock:
                pq.running.discard(request_id)
                pq.idle.discard(request_id)
                pq.cancel_requested.discard(request_id)
            self._active_requests.pop(request_id, None)
            _TURNCB.clear(request_id)
            self._drain_all()

    def _find_profile_for_request(
        self, execution_profile_id: str, request_id: str
    ) -> _RuntimeState | None:
        """Scan profile generations to find the queue tracking this request.

        Resolve the active profile generation from the provider-neutral profile id.
        """
        with self._manager_lock:
            for profile_identity, pq in self._runtime.items():
                if profile_identity.profile_id == execution_profile_id:
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

        pq = self._find_profile_for_request(execution_profile_id, request_id)
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
                        runtime.request_cancel(
                            request_id,
                            session_id=updated.get("session-id"),
                        )
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

    def queue_depth(self, execution_profile_id: str) -> dict[str, Any]:
        """Return aggregate queue depth across profile generations.

        Multiple immutable profile generations can coexist during reload; the
        provider-neutral API aggregates them for the requested profile.
        """
        pending = self._pending_authority.count(
            lambda request: request.value.execution_profile_id == execution_profile_id
        )
        running = 0
        active_running = 0
        idle = 0
        virtual_capacity = 0
        unbounded = False

        with self._manager_lock:
            for profile_identity, pq in self._runtime.items():
                if profile_identity.profile_id == execution_profile_id:
                    with pq.lock:
                        running += len(pq.running)
                        active_running += pq.active_running()
                        idle += len(pq.idle)
                    if pq.virtual_capacity is None:
                        unbounded = True
                    else:
                        virtual_capacity += pq.virtual_capacity

        return {
            "pending": pending,
            "running": running,
            "active_running": active_running,
            "idle": idle,
            "virtual_capacity": "unlimited" if unbounded else virtual_capacity,
        }

    def request_slot_status(self, execution_profile_id: str, request_id: str) -> str | None:
        pending = self._pending_authority.get(request_id)
        if pending is not None and pending.value.execution_profile_id == execution_profile_id:
            return "pending"
        pq = self._find_profile_for_request(execution_profile_id, request_id)
        if pq is None:
            return None
        with pq.lock:
            if request_id in pq.running:
                return "idle" if request_id in pq.idle else "active"
        return None

    def source_capacity_status(self) -> dict[str, dict[str, Any]]:
        """Return redacted source-capacity state for operator diagnostics."""
        return self._capacity.snapshots()

    def project_queue_depths(self, project_root: Path) -> dict[str, dict[str, int]]:
        """Return redacted queue depth grouped by execution profile for a project.

        This is the operator-facing reporting authority. It deliberately does
        not expose internal lane keys or other projects' work.
        """
        project_key = str(project_root.resolve())
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
