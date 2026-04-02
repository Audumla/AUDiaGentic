"""Provider health check helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _config_status(config: dict[str, Any]) -> tuple[bool, str | None]:
    if not config or config.get("enabled", False) is not True:
        return False, "provider not configured"
    access_mode = config.get("access-mode")
    if access_mode == "env":
        if not config.get("auth-ref"):
            return False, "auth-ref required for env access-mode"
        return True, None
    if access_mode in {"cli", "none"}:
        return True, None
    return False, "unsupported access-mode"


def health_check(provider_id: str, descriptor: dict[str, Any], config: dict[str, Any], *, now_fn=None) -> dict[str, Any]:
    configured, error = _config_status(config)
    status = "healthy" if configured else "unhealthy"
    return {
        "contract-version": "v1",
        "provider-id": provider_id,
        "status": status,
        "configured": configured,
        "latency-ms": 0,
        "error": None if configured else error,
        "checked-at": (now_fn or _now_timestamp)(),
    }
