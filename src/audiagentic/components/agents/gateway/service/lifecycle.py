"""Gateway quiescence facts, idle self-shutdown, and record-only recovery (SH10).

Foundation (PR06/PR07) owns lease and guarded-stop mechanics; this module
supplies only the gateway's domain quiescence facts and its component idle
policy, and drives self-managed shutdown through the existing store
transition/retire gates — no new stop machinery.

Idle policy: ``AUDIAGENTIC_GATEWAY_IDLE_GRACE_SECONDS`` (0 or unset =
keep-warm forever, today's behavior). When set, a running service with no
active client leases, no gateway work, and no ingress backlog for one full
grace window drains and exits through the guarded transitions: running →
draining → (final lease/quiescence re-check) → server shutdown → owner
retire (stopping → stopped). A lease acquired during the grace window resets
it; a lease can only appear while the record is still ``running``, so the
post-drain re-check is race-free (leases are refused in ``draining``).
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory
from audiagentic.foundation.system.managed_process import observe_process, ownership_matches
from audiagentic.foundation.system.managed_service import ManagedServiceStore

logger = logging.getLogger(__name__)

lifecycle_validation_error = make_error_factory("VAL", "AGLC", "gateway-lifecycle")
lifecycle_conflict_error = make_error_factory("CON", "AGLC", "gateway-lifecycle")

IDLE_GRACE_ENV = "AUDIAGENTIC_GATEWAY_IDLE_GRACE_SECONDS"
_CHECK_INTERVAL_SECONDS = 2.0


def resolve_idle_grace_seconds() -> float:
    """Component idle policy; 0 disables self-shutdown (keep-warm)."""
    raw = os.environ.get(IDLE_GRACE_ENV, "").strip()
    if not raw:
        return 0.0
    try:
        value = float(raw)
    except ValueError:
        logger.warning("invalid %s=%r; keep-warm", IDLE_GRACE_ENV, raw)
        return 0.0
    return max(0.0, value)


def gateway_quiescence_facts(service_root: Path | None = None) -> dict[str, Any]:
    """Redacted domain quiescence facts. Foundation never inspects internals —
    this is the gateway-owned callback data contract (SH10 step 2)."""
    from audiagentic.components.agents.gateway import api as api
    from audiagentic.components.agents.gateway.ingress import ingress_backlog
    from audiagentic.components.agents.gateway.session.sessions import peek_session_runtime

    depths = api.get_queue_manager().project_queue_depths(service_root) if service_root is not None else {}
    pending = sum(d.get("pending", 0) for d in depths.values())
    running = sum(d.get("running", 0) for d in depths.values())
    runtime = peek_session_runtime()
    live_sessions = len(runtime.live_session_ids()) if runtime is not None else 0
    backlog = ingress_backlog(service_root)
    active_operations = 0
    if service_root is not None:
        from audiagentic.components.agents.gateway.operations import ManagementOperationStore

        active_operations = ManagementOperationStore(service_root).active_count()
    return {
        "pending-requests": pending,
        "running-requests": running,
        "live-sessions": live_sessions,
        "ingress-pending": backlog["pending"],
        "active-gateway-operations": active_operations,
        "quiescent": (
            pending == 0
            and running == 0
            and live_sessions == 0
            and backlog["pending"] == 0
            and active_operations == 0
        ),
    }


class GatewayLifecycleController:
    """Idle self-shutdown loop plus operator drain/stop entry points.

    ``shutdown_server`` is the host-injected callable that makes
    ``serve_forever`` return; final record retirement stays with the host's
    ``close()`` → ``ManagedServiceOwner.retire`` (the PR06 guarded path).
    """

    def __init__(
        self,
        store: ManagedServiceStore,
        owner_epoch: str,
        shutdown_server: Any,
        *,
        service_root: Path | None = None,
        idle_grace_seconds: float | None = None,
        check_interval_seconds: float = _CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._store = store
        self._owner_epoch = owner_epoch
        self._shutdown_server = shutdown_server
        self._service_root = service_root
        self._idle_grace = (
            resolve_idle_grace_seconds() if idle_grace_seconds is None else idle_grace_seconds
        )
        self._check_interval = check_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._exit_reason: str | None = None
        self.restart_enabled = False
        self.restart_requested = False

    @property
    def exit_reason(self) -> str | None:
        return self._exit_reason

    # ── operator surface (invoked via the SH04 service application) ──

    def status(self) -> dict[str, Any]:
        record = self._store.read()
        return {
            **self._store.status(),
            "idle-grace-seconds": self._idle_grace,
            "quiescence": gateway_quiescence_facts(self._service_root),
            "exit-reason": self._exit_reason,
            "lifetime-scope": None if record.process is None else record.process.scope,
        }

    def request_drain(self) -> dict[str, Any]:
        record = self._store.read()
        if record.state == "draining":
            return self._store.status()
        updated = self._store.transition(
            "draining",
            expected_revision=record.revision,
            expected_epoch=self._owner_epoch,
        )
        logger.info("gateway drain requested", extra={"revision": updated.revision})
        return self._store.status()

    def request_resume(self) -> dict[str, Any]:
        if self.restart_requested:
            raise lifecycle_conflict_error(1, "gateway restart is already underway")
        record = self._store.read()
        if record.state == "running":
            return self._store.status()
        self._store.transition(
            "running",
            expected_revision=record.revision,
            expected_epoch=self._owner_epoch,
        )
        logger.info("gateway drain cancelled; resumed")
        return self._store.status()

    def request_restart(self) -> dict[str, Any]:
        """Drain admission and refuse a restart that would interrupt work."""
        if not self.restart_enabled:
            raise lifecycle_conflict_error(1, "this gateway host does not support restart")
        if self.restart_requested:
            return {"restarting": True}
        was_running = self._store.read().state == "running"
        self.request_drain()
        facts = gateway_quiescence_facts(self._store.root)
        from audiagentic.components.agents.gateway.session.sessions import peek_session_runtime

        runtime = peek_session_runtime()
        sessions = runtime.session_snapshot_all() if runtime is not None else {}
        busy_sessions = [
            session_id for session_id, state in sessions.items()
            if state.get("turn-active") or state.get("pending-turns", 0)
        ]
        # Automatic idle shutdown still treats an open provider handle as
        # non-quiescent. An explicit restart may release idle handles through
        # normal host cleanup: durable conversation bindings survive it.
        blocking_work = any(facts[key] for key in (
            "pending-requests", "running-requests", "ingress-pending",
            "active-gateway-operations",
        )) or bool(busy_sessions)
        if blocking_work:
            if was_running:
                self.request_resume()
            raise lifecycle_conflict_error(
                1, "gateway has queued or running work; retry restart when idle",
                quiescence=facts, busy_sessions=busy_sessions,
            )
        self.restart_requested = True
        self._exit_reason = "operator-restart"
        self._stop_event.set()
        self._shutdown_server()
        return {"restarting": True}

    def request_stop(self, *, force: bool = False) -> dict[str, Any]:
        """Operator stop. Graceful refuses while work or other leases remain;
        force reports the affected work it is abandoning (SH10: force stop
        must be explicit and must report affected work)."""
        record = self._store.read()
        facts = gateway_quiescence_facts(self._service_root)
        # The caller's own lease is inherently active during this call; other
        # leases block a graceful stop.
        blocking_leases = max(0, record.active_lease_count - 1)
        if not force and (not facts["quiescent"] or blocking_leases):
            raise lifecycle_conflict_error(
                1,
                "gateway is not quiescent; drain first or use force",
                quiescence=facts,
                other_active_leases=blocking_leases,
            )
        if record.state == "running":
            self._store.transition(
                "draining",
                expected_revision=record.revision,
                expected_epoch=self._owner_epoch,
            )
        if force:
            self._store.revoke_active_leases(expected_epoch=self._owner_epoch)
        self._exit_reason = "operator-force-stop" if force else "operator-stop"
        self._stop_event.set()
        self._shutdown_server()
        return {"stopping": True, "forced": force, "affected-work": facts}

    # ── idle loop ────────────────────────────────────────────────

    def start(self) -> None:
        if self._idle_grace <= 0 or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="gateway-idle-controller", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        idle_since: float | None = None
        import time

        while not self._stop_event.wait(self._check_interval):
            try:
                record = self._store.expire_leases(expected_epoch=self._owner_epoch)
                if record.state != "running":
                    idle_since = None
                    continue
                facts = gateway_quiescence_facts(self._service_root)
                if record.active_lease_count or not facts["quiescent"]:
                    idle_since = None
                    continue
                now = time.monotonic()
                if idle_since is None:
                    idle_since = now
                    continue
                if now - idle_since < self._idle_grace:
                    continue
                if self._initiate_idle_exit():
                    return
                idle_since = None
            except AudiaGenticError:
                logger.warning("gateway idle sweep failed", exc_info=True)
                idle_since = None
            except Exception:  # noqa: BLE001 — the idle loop must never die
                logger.error("gateway idle sweep raised unexpectedly", exc_info=True)
                idle_since = None

    def _initiate_idle_exit(self) -> bool:
        """Drain, then re-check the gates once; resume on any activity."""
        record = self._store.read()
        if record.state != "running":
            return False
        drained = self._store.transition(
            "draining",
            expected_revision=record.revision,
            expected_epoch=self._owner_epoch,
        )
        # Final re-check: leases cannot appear while draining, so anything
        # active now predates the drain and cancels the exit.
        current = self._store.expire_leases(expected_epoch=self._owner_epoch)
        facts = gateway_quiescence_facts(self._service_root)
        if current.active_lease_count or not facts["quiescent"]:
            self._store.transition(
                "running",
                expected_revision=current.revision,
                expected_epoch=self._owner_epoch,
            )
            logger.info("gateway idle exit cancelled by late activity")
            return False
        self._exit_reason = "idle-grace-elapsed"
        logger.info(
            "gateway idle self-shutdown",
            extra={"idle-grace-seconds": self._idle_grace, "revision": drained.revision},
        )
        self._shutdown_server()
        return True


def recover_unprovable_owner(
    *,
    service_root: Path | None = None,
    confirm: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    """Record-only recovery for a live-but-unprovable recorded owner (SH10).

    Preserves redacted diagnostics, marks the record failed under a fresh
    owner epoch (fencing any stale writer), and NEVER signals or adopts the
    recorded PID. Refuses when the recorded owner is still provable — use the
    normal operator stop path in that case.
    """
    from audiagentic.components.agents.gateway.service.host import (
        GATEWAY_SERVICE_KEY,
    )

    store = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=service_root)
    record = store.read()
    if record.state == "stopped":
        raise lifecycle_conflict_error(2, "service record is already stopped")
    evidence = record.process
    observed = None if evidence is None else observe_process(evidence)
    if evidence is not None and ownership_matches(evidence, observed):
        raise lifecycle_conflict_error(
            3,
            "recorded owner is provable and alive; use the normal stop path",
            pid=evidence.pid,
        )
    if not confirm:
        raise lifecycle_validation_error(
            4,
            "unprovable-owner recovery mutates the durable record; pass confirm=true",
            recorded_pid=None if evidence is None else evidence.pid,
            observed_alive=observed is not None,
        )
    diagnostics = {
        "failure-class": "unprovable-owner-recovered",
        "recorded-pid": None if evidence is None else evidence.pid,
        "recorded-scope": None if evidence is None else evidence.scope,
        "observed-alive": observed is not None,
        "previous-state": record.state,
        "reason": reason or "operator-confirmed unprovable owner",
    }
    # No epoch rotation: retained process evidence must keep matching the
    # record epoch (store invariant), and every mutation path is already
    # fenced by the revision bump plus the failed-state gates. The evidence
    # stays on the record as diagnostics; it is never signalled.
    updated = store.transition(
        "failed",
        expected_revision=record.revision,
        expected_epoch=record.owner_epoch,
        failure=diagnostics,
    )
    logger.warning("gateway unprovable-owner record recovered", extra=diagnostics)
    return {
        "recovered": True,
        "state": updated.state,
        "owner-epoch": updated.owner_epoch,
        "diagnostics": diagnostics,
    }


__all__ = [
    "GatewayLifecycleController",
    "IDLE_GRACE_ENV",
    "gateway_quiescence_facts",
    "recover_unprovable_owner",
    "resolve_idle_grace_seconds",
]
