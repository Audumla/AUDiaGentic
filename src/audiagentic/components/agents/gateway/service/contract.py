"""Neutral constants for the authenticated standalone gateway v1 protocol."""

from __future__ import annotations

PROTOCOL_VERSION = "gateway-service-v2"
HEALTH_ROUTE = "/v1/health"
CALL_ROUTE = "/v1/call"
LEASE_ACQUIRE_ROUTE = "/v1/client-leases/acquire"
LEASE_RENEW_ROUTE = "/v1/client-leases/renew"
LEASE_RELEASE_ROUTE = "/v1/client-leases/release"
MAX_LEASE_TTL_SECONDS = 300.0

__all__ = [
    "CALL_ROUTE",
    "HEALTH_ROUTE",
    "LEASE_ACQUIRE_ROUTE",
    "LEASE_RELEASE_ROUTE",
    "LEASE_RENEW_ROUTE",
    "MAX_LEASE_TTL_SECONDS",
    "PROTOCOL_VERSION",
]
