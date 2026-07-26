"""Public API surface for the core session component."""

from __future__ import annotations

import os
import platform
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.session_status import (
    ProviderSessionInfo,
)

from . import session_embedded_rig, session_runtime_status

_UPDATE_SCOPE_REGISTRY: dict[str, Callable[..., Any]] = {
    "local": session_embedded_rig.update_embedded_rig,
    "global": session_embedded_rig.update_global_embedded_rig,
}


def _resolve_session_info(project_root: Path) -> ProviderSessionInfo:
    """Resolve provider session info from runtime capability.

    RU02: runtime resolves, session consumes — no rig queries in product components.
    """
    from audiagentic.foundation.capabilities import get_harness_status

    hs = get_harness_status()
    return hs["resolve_session_info"](project_root)


def status(project_root: Path) -> dict[str, Any]:
    """Return current harness/session status."""
    ctx = _resolve_session_info(project_root)
    try:
        model = session_runtime_status.model_info(ctx)
    except Exception as exc:  # noqa: BLE001 - status should remain inspectable.
        model = {
            "configured": False,
            "error": str(exc),
        }
    return {
        "versions": session_runtime_status.versions(ctx),
        "model": model,
        "endpoint": session_runtime_status.endpoint_info(ctx),
        "auto_update": _auto_update_status(),
        "environment": {
            "repo_root": str(project_root),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "cwd": str(Path.cwd()),
        },
    }


def config() -> dict[str, Any]:
    """Return current harness config and materialized model metadata."""
    from pathlib import Path

    ctx = _resolve_session_info(Path.cwd())
    return session_runtime_status.harness_config(ctx)


def set_auto_update(enabled: bool) -> dict[str, Any]:
    """Enable or disable launch-time auto update checks."""
    env_var = "AUDIAGENTIC_AUTO_UPDATE_ENABLED"
    os.environ[env_var] = str(enabled).lower()
    return {"ok": True, "auto_update_enabled": enabled, "env": env_var}


def refresh_harness_config(project_root: Path) -> dict[str, Any]:
    """Regenerate harness config and return runtime sync instructions."""
    from audiagentic.foundation.capabilities import get_harness_status

    hs = get_harness_status()
    refreshed = hs["refresh_harness_config_if_installed"](project_root, reason="mcp-refresh-tool")
    return {
        "ok": refreshed,
        "refreshed": refreshed,
        "sync": hs["build_runtime_sync"](reason="mcp-refresh-tool"),
    }


async def update_rig(*, scope: str = "local") -> dict[str, Any]:
    """Update rig binaries for the requested scope."""
    if os.environ.get("AUDIAGENTIC_MCP_SMOKE_ONLY") == "1":
        return {
            "ok": True,
            "output": "smoke-only: rig update skipped",
            "scope": scope,
        }
    handler = _UPDATE_SCOPE_REGISTRY.get(scope)
    if handler is None:
        return {
            "ok": False,
            "error": "scope must be 'local' or 'global'",
            "scope": scope,
        }
    return await handler()


def _auto_update_status() -> dict[str, Any]:
    from audiagentic.runtime.update.checker import check_update, current_version

    payload: dict[str, Any] = {
        "installed_version": current_version(),
        "enabled": os.environ.get("AUDIAGENTIC_AUTO_UPDATE_ENABLED", "true").lower() == "true",
    }
    update = check_update(force=True)
    if update:
        payload["latest_version"] = update["latest"]
        payload["available"] = True
    else:
        payload["latest_version"] = payload["installed_version"]
        payload["available"] = False
    return payload
