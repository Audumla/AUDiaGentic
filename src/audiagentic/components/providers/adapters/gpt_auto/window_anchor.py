"""Gateway-dashboard URL for GPT-auto's dedicated-window anchor."""

from __future__ import annotations

import os


def gateway_dashboard_url() -> str:
    """Resolve the gateway-owned dashboard without importing gateway internals."""
    explicit = os.environ.get("AUDIAGENTIC_GATEWAY_DASHBOARD_URL")
    if explicit:
        return explicit.rstrip("/")
    port = os.environ.get("AUDIAGENTIC_GATEWAY_PORT", "8765")
    path = os.environ.get("AUDIAGENTIC_GATEWAY_DASHBOARD_PATH", "/dashboard")
    return f"http://127.0.0.1:{port}/{path.lstrip('/')}"


__all__ = ["gateway_dashboard_url"]
