"""Standalone gateway host composition and managed-service ownership."""
from __future__ import annotations

import logging
import os
import secrets
import threading
from pathlib import Path

from audiagentic.components.agents.agents_gateway_application import (
    GatewayApplication,
    get_gateway_application,
)
from audiagentic.components.agents.agents_gateway_http_transport import GatewayHTTPServer
from audiagentic.components.agents.agents_gateway_remote_client import load_auth_token
from audiagentic.components.agents.agents_gateway_service_application import (
    GatewayServiceApplication,
)
from audiagentic.components.agents.agents_gateway_service_contract import PROTOCOL_VERSION
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import current_process_evidence
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import EndpointInfo, ServiceKey
from audiagentic.foundation.system.managed_service_owner import ManagedServiceOwner

logger = logging.getLogger(__name__)
GATEWAY_SERVICE_KEY = ServiceKey("agent-llm-gateway", "default")


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

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address
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
        gateway_profiles_config: Path | None = None,
    ) -> GatewayServiceHost:
        if host != "127.0.0.1" or isinstance(port, bool) or not 0 <= port <= 65535:
            from audiagentic.components.agents.agents_gateway_http_transport import transport_error

            if host != "127.0.0.1":
                raise transport_error(3, "gateway service must bind to IPv4 loopback")
            raise transport_error(17, "gateway service port is outside the valid range", port=port)
        # SH07 C2/RV745: the gateway host is the composition root for the
        # gateway-owned profile registry. Load it from the machine-scoped
        # config before any request can be admitted so shared-mode queue
        # limits/generations are gateway-authoritative from first request.
        from audiagentic.components.agents import (
            agents_gateway_profiles as profiles_mod,
        )
        from audiagentic.foundation.paths.home import global_config_dir

        resolved_profiles_config = (
            gateway_profiles_config or global_config_dir() / "gateway-profiles.yaml"
        )
        registry = profiles_mod.load_gateway_registry_from_config(resolved_profiles_config)
        profiles_mod.set_gateway_registry(registry)
        # SH13 step 3: record the config path so reload can re-read the source
        profiles_mod.set_gateway_registry_config_path(
            resolved_profiles_config if registry is not None else None
        )

        store = ManagedServiceStore(GATEWAY_SERVICE_KEY, root=service_root)
        resolved_token_path = token_path or store.root / "auth.token"
        token = load_or_create_auth_token(resolved_token_path)
        domain_application = application or get_gateway_application()
        service_application = GatewayServiceApplication(domain_application, store)
        server = GatewayHTTPServer((host, port), service_application, token)
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
        # SH10: bind the lifecycle controller now that the owner epoch is
        # known; the host is the composition root for both objects.
        from audiagentic.components.agents.agents_gateway_lifecycle import (
            GatewayLifecycleController,
        )

        lifecycle = GatewayLifecycleController(
            store,
            record.owner_epoch,
            server.shutdown,
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
        )

    def serve_forever(self) -> None:
        # SH07: reconcile durable active work from the prior service generation
        # BEFORE readiness and before ingress admits new work. A recovery
        # failure propagates and prevents the service from reporting ready.
        from audiagentic.components.agents.agents_gateway_recovery import (
            recover_gateway_requests,
        )

        recover_gateway_requests(
            self.service_store.root, live_owner_epoch=self.owner_epoch
        )
        if not self._externally_managed:
            self.service_store.heartbeat(
                {"ready": True}, expected_epoch=self.owner_epoch
            )
        self._start_ingress_poller()
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
        from audiagentic.components.agents.agents_gateway_ingress import (
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
        if self.lifecycle is not None:
            self.lifecycle.stop()  # type: ignore[attr-defined]

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_background()
        from audiagentic.components.agents import (
            agents_gateway_profiles as profiles_mod,
        )

        profiles_mod.set_gateway_registry(None)
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
