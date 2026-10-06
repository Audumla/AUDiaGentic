"""Standalone gateway host composition and managed-service ownership."""

from __future__ import annotations

import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Any

from audiagentic.components.agents.gateway.application import (
    GatewayApplication,
)
from audiagentic.components.agents.gateway.remote_client import load_auth_token
from audiagentic.components.agents.gateway.service.application import (
    GatewayServiceApplication,
)
from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION
from audiagentic.components.agents.gateway.service.http_transport import GatewayHTTPServer
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import current_process_evidence
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import EndpointInfo, ServiceKey
from audiagentic.foundation.system.managed_service_owner import ManagedServiceOwner
from audiagentic.foundation.time import now_iso_z

logger = logging.getLogger(__name__)
GATEWAY_SERVICE_KEY = ServiceKey("agent-execution-gateway", "default")


class GatewayServiceHost:
    """Own the HTTP adapter and publish this process through foundation lifecycle."""

    def __init__(
        self,
        server: GatewayHTTPServer,
        service_store: ManagedServiceStore,
        owner: ManagedServiceOwner,
        owner_epoch: str,
        token_path: Path,
        externally_managed: bool = False,
        *,
        application: GatewayApplication | None = None,
        lifecycle: object | None = None,
        service_root: Path | None = None,
        composition_graph: object | None = None,
    ) -> None:
        self.server = server
        self.service_store = service_store
        self.owner = owner
        self.owner_epoch = owner_epoch
        self.token_path = token_path
        self._externally_managed = externally_managed
        self._closed = False
        self._application = application
        self.lifecycle = lifecycle
        self._service_root = service_root
        self._ingress_stop = threading.Event()
        self._ingress_thread: threading.Thread | None = None
        self._operations_stop = threading.Event()
        self._operations_thread: threading.Thread | None = None
        # AS60 step 7 / RV888: this process's own composition root. Shutdown
        # uninstalls the shared-gateway execution-profile registry.
        self._composition_graph = composition_graph

    @property
    def endpoint(self) -> str:
        host = str(self.server.server_address[0])
        port: int = self.server.server_address[1]
        return f"http://{host}:{port}"

    @classmethod
    def create(
        cls,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        token_path: Path | None = None,
        application: GatewayApplication | None = None,
        service_root: Path | None = None,
    ) -> GatewayServiceHost:
        if host != "127.0.0.1" or isinstance(port, bool) or not 0 <= port <= 65535:
            from audiagentic.components.agents.gateway.service.http_transport import transport_error

            if host != "127.0.0.1":
                raise transport_error(3, "gateway service must bind to IPv4 loopback")
            raise transport_error(17, "gateway service port is outside the valid range", port=port)
        # AS60 step 7 / RV888: build this process's own composition root
        # before any request can be admitted, so shared-mode queue
        # limits/generations are gateway-authoritative from first request.
        # This process (not the CLI/launcher) is the second, deliberate root
        # Stage 1 anticipated -- see gateway_service_composition.py.
        from audiagentic.components.agents.gateway.service.dashboard import (
            recent_window_seconds,
        )
        from audiagentic.runtime.bootstrap.gateway_service_composition import (
            build_gateway_application,
            build_gateway_service_graph,
        )

        composition_graph = build_gateway_service_graph()
        try:
            store = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=service_root)
            resolved_token_path = token_path or store.root / "auth.token"
            token = load_or_create_auth_token(resolved_token_path)
            domain_application = application or build_gateway_application()
            configured_recent_seconds = recent_window_seconds()
            service_application = GatewayServiceApplication(
                domain_application,
                store,
                dashboard_recent_seconds=configured_recent_seconds,
            )
            server = GatewayHTTPServer(
                (host, port),
                service_application,
                token,
                dashboard_path=os.environ.get("AUDIAGENTIC_GATEWAY_DASHBOARD_PATH", "/dashboard"),
                dashboard_recent_seconds=configured_recent_seconds,
            )
            owner = ManagedServiceOwner(store)
            address = f"{server.server_address[0]}:{server.server_address[1]}"
            managed_epoch = os.environ.get("AUDIAGENTIC_SERVICE_OWNER_EPOCH")
            try:
                if managed_epoch:
                    record = store.read()
                    if record.owner_epoch != managed_epoch:
                        from audiagentic.foundation.system.managed_service_contracts import (
                            conflict_error,
                        )

                        raise conflict_error(22, "managed gateway owner epoch does not match")
                    expected_endpoint = EndpointInfo("loopback-http", address, "gateway-auth-v1")
                    if record.endpoint != expected_endpoint:
                        from audiagentic.foundation.system.managed_service_contracts import (
                            conflict_error,
                        )

                        raise conflict_error(24, "managed gateway endpoint does not match")
                else:
                    record = owner.claim(
                        protocol_version=PROTOCOL_VERSION,
                        endpoint=EndpointInfo("loopback-http", address, "gateway-auth-v1"),
                        evidence_factory=lambda epoch: current_process_evidence(
                            owner_epoch=epoch, scope="shared-service-host"
                        ),
                        health_facts={"ready": False},
                    )
            except Exception:
                server.server_close()
                raise
        except Exception:
            # This process's composition root: a failure after the graph is
            # built but before the host object exists must still uninstall
            # the registry the graph's factory just installed.
            composition_graph.shutdown()
            raise
        # SH10: bind the lifecycle controller now that the owner epoch is
        # known; the host is the composition root for both objects.
        from audiagentic.components.agents.gateway.service.lifecycle import (
            GatewayLifecycleController,
        )

        # ``BaseServer.shutdown`` blocks until ``serve_forever`` unwinds.  A
        # lifecycle request arrives on an HTTP handler thread, so invoke it
        # from a separate helper thread; calling it inline deadlocks the
        # handler and leaves the durable service record stuck in draining.
        def _shutdown_from_lifecycle() -> None:
            threading.Thread(
                target=server.shutdown, name="gateway-server-shutdown", daemon=True
            ).start()

        lifecycle = GatewayLifecycleController(
            store,
            record.owner_epoch,
            _shutdown_from_lifecycle,
            service_root=service_root,
        )
        service_application._lifecycle = lifecycle
        return cls(
            server,
            store,
            owner,
            record.owner_epoch,
            resolved_token_path,
            externally_managed=managed_epoch is not None,
            application=domain_application,
            lifecycle=lifecycle,
            service_root=service_root,
            composition_graph=composition_graph,
        )

    def serve_forever(self) -> None:
        # SH07: reconcile durable active work from the prior service generation
        # BEFORE readiness and before ingress admits new work. A recovery
        # failure propagates and prevents the service from reporting ready.
        from audiagentic.components.agents.gateway.queue.recovery import (
            recover_gateway_requests,
        )

        recovery_report = recover_gateway_requests(
            self.service_store.root, live_owner_epoch=self.owner_epoch
        )
        # Rebuild the process-local scheduler only after durable ownership has
        # been taken over.  This keeps queued work claimable once and gives
        # already-running work the dedicated observation/recovery path.
        if recovery_report.queued or recovery_report.running:
            from audiagentic.components.agents.gateway import api as gateway_api
            from audiagentic.components.agents.gateway.queue.recovery import recovery_runner

            queue_manager = gateway_api.get_queue_manager()
            for project_root, request_id in recovery_report.queued:
                record = gateway_api.store.read_record(project_root, request_id)
                runtime = record.get("gateway-profile-runtime") or {}
                queue_manager.enqueue_recovered_queued(
                    project_root,
                    record,
                    dict(runtime.get("params") or {}),
                    recovery_runner(record, project_root=project_root),
                    dispatch_owner_epoch=self.owner_epoch,
                    dispatch_service_root=self.service_store.root,
                )
            for project_root, request_id in recovery_report.running:
                record = gateway_api.store.read_record(project_root, request_id)
                runtime = record.get("gateway-profile-runtime") or {}
                queue_manager.enqueue_recovered_running(
                    project_root,
                    record,
                    dict(runtime.get("params") or {}),
                    recovery_runner(record, project_root=project_root),
                    dispatch_owner_epoch=self.owner_epoch,
                    dispatch_service_root=self.service_store.root,
                )
        # GP26: machine-level gpt-auto config drift detection runs after durable
        # request recovery (correctness-critical) and before readiness. An
        # invalid MACHINE-level config is fatal (it is the shared foundation);
        # an invalid PROJECT config blocks only that project, never the gateway.
        from audiagentic.components.agents.gateway.service.known_projects import (
            scan_known_gpt_auto_projects,
        )
        from audiagentic.components.providers.adapters.gpt_auto.config import (
            validate_machine_gpt_auto_config,
            validate_project_gpt_auto_config,
        )

        validate_machine_gpt_auto_config()
        scan_known_gpt_auto_projects(
            self.service_store.root / "known-projects.json",
            check_project=validate_project_gpt_auto_config,
        )
        if not self._externally_managed:
            self.service_store.heartbeat({"ready": True}, expected_epoch=self.owner_epoch)
        self._start_ingress_poller()
        self._start_operations_poller()
        if self.lifecycle is not None:
            self.lifecycle.start()  # type: ignore[attr-defined]
        try:
            self.server.serve_forever(poll_interval=0.1)
        finally:
            self._stop_background()

    def shutdown(self) -> None:
        self.server.shutdown()

    def _start_ingress_poller(self, interval_seconds: float = 1.0) -> None:
        """SH09: drain the durable trigger spool while the service runs."""
        if self._application is None or self._ingress_thread is not None:
            return
        from audiagentic.components.agents.gateway.ingress import (
            drain_gateway_ingress,
        )

        def _poll() -> None:
            while not self._ingress_stop.wait(interval_seconds):
                drain_gateway_ingress(self._application, service_root=self._service_root)

        # Startup drain first: triggers spooled while the service was down are
        # admitted before the poller cadence begins.
        drain_gateway_ingress(self._application, service_root=self._service_root)
        self._ingress_thread = threading.Thread(
            target=_poll, name="gateway-ingress-poller", daemon=True
        )
        self._ingress_thread.start()

    def _stop_background(self) -> None:
        self._ingress_stop.set()
        if self._ingress_thread is not None:
            self._ingress_thread.join(timeout=5.0)
            self._ingress_thread = None
        self._operations_stop.set()
        if self._operations_thread is not None:
            self._operations_thread.join(timeout=5.0)
            self._operations_thread = None
        if self.lifecycle is not None:
            self.lifecycle.stop()  # type: ignore[attr-defined]

    def _start_operations_poller(self, interval_seconds: float = 1.0) -> None:
        """Run durable gateway operations from the one service authority."""
        if self._application is None or self._operations_thread is not None:
            return
        from audiagentic.components.agents.gateway.operations import (
            GatewayOperationExecutor,
            ManagementOperationPump,
            ManagementOperationStore,
        )

        pump = ManagementOperationPump(
            ManagementOperationStore(self.service_store.root),
            GatewayOperationExecutor(self._application),
        )

        def _poll() -> None:
            while not self._operations_stop.wait(interval_seconds):
                pump.run_once(owner_epoch=self.owner_epoch)
                self.run_watchdog_pass()

        # Startup scan makes notifier loss and host restart harmless.
        pump.run_once(owner_epoch=self.owner_epoch)
        self._operations_thread = threading.Thread(
            target=_poll, name="gateway-operations-poller", daemon=True
        )
        self._operations_thread.start()

    def run_watchdog_pass(self) -> tuple[dict[str, Any], ...]:
        """Diagnose running work and revalidate stale live transports safely.

        Revalidation is intentionally limited to an already-owned active turn
        and an optional provider transport seam. It never resubmits a prompt;
        the ordinary activity relay must still prove that the turn resumed.
        """
        from audiagentic.components.agents.gateway import store
        from audiagentic.components.agents.gateway.api import (
            complete_execution_from_provider,
            recover_execution_request,
        )
        from audiagentic.components.agents.gateway.queue.dispatch import diagnose_activity_lease
        from audiagentic.components.agents.gateway.queue.watchdog_policy import load_watchdog_policy
        from audiagentic.components.agents.gateway.queue.watchdog_registry import watchdog_registry
        from audiagentic.components.agents.gateway.session import sessions_store
        from audiagentic.components.agents.gateway.session.sessions import peek_session_runtime

        def _retire_unbound_initial_timeout(updated: dict[str, Any]) -> dict[str, Any]:
            """Terminalize an orphaned attempt only when no provider side effect is possible.

            A watchdog observation is not proof that a prompt failed.  The
            exception here is deliberately narrow: the initial observation
            expired, the session never acquired a durable provider binding,
            the provider did not report an unresolved turn, and the session is
            not live in this gateway process.  Keeping that combination in
            ``running`` otherwise permanently consumes queue capacity.
            """
            if updated.get("state") != "running" or updated.get("watchdog-reason") != "initial-activity-observation-expired":
                return updated
            session_id = updated.get("session-id")
            if not isinstance(session_id, str) or not session_id:
                return updated
            diagnostics = updated.get("diagnostics")
            if not isinstance(diagnostics, dict) or diagnostics.get("resolution-state") != "unresolved":
                return updated
            try:
                session = sessions_store.read_session_record(project_root, session_id)
            except Exception:  # noqa: BLE001 - watchdog recovery is best effort
                return updated
            if session.get("binding"):
                return updated
            metadata = sessions_store.session_provider_metadata(session)
            if metadata.get("unresolved-turn-pending"):
                return updated
            if runtime is not None:
                try:
                    if runtime.session_runtime_status(session_id).get("available"):
                        return updated
                except Exception:  # noqa: BLE001 - retain reconcile-only behavior on probe failure
                    return updated
            from datetime import datetime, timedelta, timezone
            try:
                diagnosed_at = datetime.fromisoformat(str(updated.get("updated-at")).replace("Z", "+00:00"))
                if diagnosed_at.tzinfo is None:
                    diagnosed_at = diagnosed_at.replace(tzinfo=timezone.utc)
                policy = updated.get("watchdog-policy")
                grace = float(policy.get("diagnostic-grace-seconds", 30.0)) if isinstance(policy, dict) else load_watchdog_policy().diagnostic_grace_seconds
                if datetime.now(timezone.utc) < diagnosed_at + timedelta(seconds=max(grace, 1.0)):
                    return updated
            except (TypeError, ValueError, OverflowError):
                return updated
            error = {
                "code": "RES-AGW-003",
                "kind": "agents",
                "message": "provider session binding was not established before the initial activity window expired",
                "details": {
                    "session-id": session_id,
                    "failure-reason": "provider-binding-not-established",
                    "watchdog-reason": "initial-activity-observation-expired",
                    "retry-safe": True,
                    "suggestion": "retry the request; no provider conversation binding or unresolved turn was found",
                },
            }
            try:
                retired = store.transition_owned_terminal(
                    project_root,
                    updated["request-id"],
                    "failed",
                    updates={
                        "error": error,
                        "recovery": {"reason": "unproven-execution", "outcome": "resubmit-required"},
                    },
                    owner_epoch=updated["dispatch-owner-epoch"],
                    worker_id=updated["worker-id"],
                    attempt_epoch=updated["attempt-epoch"],
                    expected_revision=updated.get("revision"),
                )
            except Exception:  # noqa: BLE001 - a live worker or newer owner wins the race
                return store.read_record(project_root, updated["request-id"])
            try:
                if session.get("state") == "active":
                    sessions_store.transition_session_record(
                        project_root,
                        session_id,
                        "failed",
                        updates={"close-reason": "failed"},
                    )
            except Exception:  # noqa: BLE001 - request terminal state remains authoritative
                logger.warning("failed to retire orphaned gateway session", extra={"session-id": session_id}, exc_info=True)
            return retired

        registry = watchdog_registry()
        runtime = peek_session_runtime()
        results: list[dict[str, Any]] = []
        for project_root, record in registry.snapshot():
            updated = diagnose_activity_lease(project_root, record)
            registry.update(project_root, updated)
            if (
                updated.get("state") == "running"
                and updated.get("cancel-requested") is True
                and isinstance(updated.get("session-id"), str)
            ):
                session_id = str(updated["session-id"])
                try:
                    session = sessions_store.read_session_record(project_root, session_id)
                except Exception:  # noqa: BLE001 - a missing record is not proof the turn stopped
                    session = None
                session_terminal = isinstance(session, dict) and session.get("state") in {
                    "closed",
                    "failed",
                    "expired",
                }
                runtime_available = False
                if runtime is not None:
                    try:
                        runtime_available = bool(
                            runtime.session_runtime_status(session_id).get("available")
                        )
                    except Exception:  # noqa: BLE001 - retain the durable session fact
                        runtime_available = False
                # Cancellation is terminal intent. Once the owning runtime is
                # gone, do not require the detached session record to close
                # first or the request can remain running forever.
                if not runtime_available:
                    try:
                        updated = store.transition_owned_terminal(
                            project_root,
                            updated["request-id"],
                            "cancelled",
                            updates={
                                "error": {
                                    "code": "CON-AGW-CANCELLED",
                                    "kind": "agents",
                                    "message": "gateway request cancellation confirmed after session closure",
                                },
                                "finished-at": now_iso_z(),
                            },
                            owner_epoch=updated["dispatch-owner-epoch"],
                            worker_id=updated["worker-id"],
                            attempt_epoch=updated["attempt-epoch"],
                            expected_revision=updated.get("revision"),
                        )
                    except Exception:  # noqa: BLE001 - a live worker or newer owner wins
                        updated = store.read_record(project_root, updated["request-id"])
                    registry.update(project_root, updated)
            updated = _retire_unbound_initial_timeout(updated)
            registry.update(project_root, updated)
            diagnostics = updated.get("diagnostics")
            if (
                updated.get("watchdog-state") == "intervention"
                and isinstance(updated.get("session-id"), str)
                and isinstance(diagnostics, dict)
                and diagnostics.get("resolution-state")
                in {"unresolved", "reconciliation-requested"}
            ):
                # A quiet provider turn can already be complete even when its
                # activity observer died. Reconcile the durable request from
                # the provider DOM before merely refreshing the transport;
                # otherwise the old running record keeps the session fence
                # and every later request waits forever behind it.
                try:
                    captured = complete_execution_from_provider(
                        project_root, updated["request-id"]
                    )
                except Exception:  # noqa: BLE001 - an incomplete turn remains recoverable
                    captured = None
                if isinstance(captured, dict) and captured.get("state") in {
                    "completed",
                    "failed",
                    "cancelled",
                    "interrupted",
                }:
                    try:
                        updated = store.read_record(project_root, updated["request-id"])
                        registry.update(project_root, updated)
                    except Exception:  # noqa: BLE001 - watchdog recovery is advisory
                        logger.warning(
                            "automatic provider completion could not refresh durable state",
                            extra={"request-id": updated.get("request-id")},
                            exc_info=True,
                        )
                elif runtime is not None:
                    outcome = runtime.reconcile_active_transport(
                        updated["session-id"], updated["request-id"]
                    )
                    if outcome.get("status") == "reconciled":
                        try:
                            recover_execution_request(
                                project_root,
                                updated["request-id"],
                                action="reconcile",
                                expected_revision=updated.get("revision"),
                            )
                            updated = store.read_record(project_root, updated["request-id"])
                            registry.update(project_root, updated)
                        except Exception:  # noqa: BLE001 - watchdog recovery is advisory
                            logger.warning(
                                "automatic transport reconciliation could not persist intent",
                                extra={"request-id": updated.get("request-id")},
                                exc_info=True,
                            )
            results.append(updated)
            if updated.get("state") in {"completed", "failed", "cancelled", "interrupted"}:
                registry.unregister(project_root, str(updated.get("request-id", "")))
        return tuple(results)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_background()
        if self._composition_graph is not None:
            self._composition_graph.shutdown()  # type: ignore[attr-defined]
        self.server.server_close()
        try:
            self.owner.retire(expected_epoch=self.owner_epoch)
        except AudiaGenticError:
            logger.warning(
                "gateway service owner record could not retire cleanly",
                extra={"service_kind": GATEWAY_SERVICE_KEY.service_kind},
                exc_info=True,
            )

    def __enter__(self) -> GatewayServiceHost:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def load_or_create_auth_token(path: Path) -> str:
    """Create one private token file or reuse the existing explicit credential."""
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return load_auth_token(path)
    try:
        os.write(descriptor, token.encode("utf-8"))
    finally:
        os.close(descriptor)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


__all__ = ["GATEWAY_SERVICE_KEY", "GatewayServiceHost", "load_or_create_auth_token"]
