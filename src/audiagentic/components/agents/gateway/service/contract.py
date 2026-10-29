"""Neutral constants for the authenticated standalone gateway v1 protocol."""

from __future__ import annotations

from audiagentic.foundation.system.managed_service_contracts import ServiceKey

GATEWAY_SERVICE_KEY = ServiceKey("agent-execution-gateway", "default")

PROTOCOL_VERSION = "gateway-service-v3"
HEALTH_ROUTE = "/v1/health"
CALL_ROUTE = "/v1/call"
LEASE_ACQUIRE_ROUTE = "/v1/client-leases/acquire"
LEASE_RENEW_ROUTE = "/v1/client-leases/renew"
LEASE_RELEASE_ROUTE = "/v1/client-leases/release"
MAX_LEASE_TTL_SECONDS = 300.0

__all__ = [
    "CALL_ROUTE",
    "GATEWAY_SERVICE_KEY",
    "HEALTH_ROUTE",
    "LEASE_ACQUIRE_ROUTE",
    "LEASE_RELEASE_ROUTE",
    "LEASE_RENEW_ROUTE",
    "MAX_LEASE_TTL_SECONDS",
    "PROTOCOL_VERSION",
]
