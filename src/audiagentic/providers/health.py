"""Provider health check helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def health_check(provider_id: str, descriptor: dict[str, Any], config: dict[str, Any], *, now_fn=None) -> dict[str, Any]:
    configured = bool(config) and config.get("enabled", False) is True
    status = "healthy" if configured else "unhealthy"
    return {
        "contract-version": "v1",
        "provider-id": provider_id,
        "status": status,
        "configured": configured,
        "latency-ms": 0,
        "error": None if configured else "provider not configured",
        "checked-at": (now_fn or _now_timestamp)(),
    }
