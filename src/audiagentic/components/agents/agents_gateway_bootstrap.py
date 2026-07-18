"""Gateway-specific declaration over foundation managed-service lifecycle."""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_gateway_remote_client import (
    StandaloneGatewayClient,
    load_auth_token,
)
from audiagentic.components.agents.agents_gateway_service_contract import PROTOCOL_VERSION
from audiagentic.components.agents.agents_gateway_service_host import GATEWAY_SERVICE_KEY
from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.system.managed_process import DetachedLaunch
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import EndpointInfo
from audiagentic.foundation.system.managed_service_lifecycle import (
    ManagedServiceDeclaration,
    ManagedServiceHooks,
    ManagedServiceLifecycle,
    ServiceHandshake,
)

_DEFAULT_PORT = 8765
_LEASE_TTL_SECONDS = 120.0
_config_error = make_error_factory("CFG", "AGSV", "gateway-service")


def start_or_attach_gateway() -> StandaloneGatewayClient:
    """Start one compatible machine-wide gateway or attach to its proven owner."""
    port = _configured_port()
    store = ManagedServiceStore(GATEWAY_SERVICE_KEY)
    endpoint_info = EndpointInfo(
        "loopback-http", f"127.0.0.1:{port}", "gateway-auth-v1"
    )
    endpoint = f"http://{endpoint_info.address}"
    # The service is machine-scoped, not an extension of the starter's project.
    # Its per-request canonical root and component profile travel on the gateway
    # request instead, so it must not inherit either from whichever client wins
    # cold start.
    store.root.mkdir(parents=True, exist_ok=True)
    token_path = store.root / "auth.token"
    declaration = ManagedServiceDeclaration(
        key=GATEWAY_SERVICE_KEY,
        process=DetachedLaunch(
            (
                sys.executable,
                "-m",
                "audiagentic.components.agents.agents_gateway_service_process",
                "--port",
                str(port),
                "--token-file",
                str(token_path),
            ),
            cwd=store.root,
            env={
                "AUDIAGENTIC_REPO_ROOT": "",
                "AUDIAGENTIC_COMPONENT_PROFILE": "",
            },
        ),
        endpoint=endpoint_info,
        protocol_version=PROTOCOL_VERSION,
    )
    lifecycle = ManagedServiceLifecycle(
        store,
        ManagedServiceHooks(
            handshake=lambda record: _handshake(record, endpoint, token_path),
            quiescent=lambda _record: False,
            request_stop=lambda _record: None,
        ),
    )
    result = lifecycle.start_or_attach(
        declaration,
        client_instance_id=f"gateway-client-{uuid.uuid4().hex[:16]}",
        lease_ttl_seconds=_LEASE_TTL_SECONDS,
        lease_facts={"client": "audiagentic"},
    )
    client = StandaloneGatewayClient(
        endpoint,
        load_auth_token(token_path),
        lease_ttl_seconds=_LEASE_TTL_SECONDS,
    )
    if result.record.process is None:
        raise _config_error(4, "managed gateway has no process lifetime evidence")
    client.adopt_managed_lease(
        result.lease.lease_id,
        result.record.owner_epoch,
        lifetime_scope=result.record.process.scope,
    )
    return client


def _handshake(record: Any, endpoint: str, token_path: Path) -> ServiceHandshake:
    client = StandaloneGatewayClient(endpoint, load_auth_token(token_path))
    health = client.health()
    return ServiceHandshake(
        ready=health.get("state") in {"starting", "running"},
        owner_epoch=str(health.get("owner-epoch", "")),
        protocol_version=str(health.get("protocol-version", "")),
        endpoint=record.endpoint,
        health_facts={"ready": True, "capabilities": health.get("capabilities", [])},
    )


def _configured_port() -> int:
    raw = os.environ.get("AUDIAGENTIC_GATEWAY_PORT", str(_DEFAULT_PORT))
    try:
        port = int(raw)
    except ValueError as exc:
        raise _config_error(3, "automatic gateway port is invalid", value=raw) from exc
    if not 1 <= port <= 65535:
        raise _config_error(3, "automatic gateway port is outside the valid range", port=port)
    return port


__all__ = ["start_or_attach_gateway"]
