"""Public API surface for the core session component."""

from __future__ import annotations

import os
import platform
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.runtime.harness import build_runtime_sync, refresh_harness_config_if_installed

from . import session_embedded_rig, session_runtime_status

_UPDATE_SCOPE_REGISTRY: dict[str, Callable[..., Any]] = {
    "local": session_embedded_rig.update_embedded_rig,
    "global": session_embedded_rig.update_global_embedded_rig,
}


def status(project_root: Path) -> dict[str, Any]:
    """Return current harness/session status."""
    try:
        model = session_runtime_status.model_info()
    except Exception as exc:  # noqa: BLE001 - status should remain inspectable.
        model = {
            "configured": False,
            "error": str(exc),
        }
    return {
        "versions": session_runtime_status.versions(),
        "model": model,
        "endpoint": session_runtime_status.endpoint_info(),
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
    return session_runtime_status.harness_config()


def set_auto_update(enabled: bool) -> dict[str, Any]:
    """Enable or disable launch-time auto update checks."""
    env_var = "AUDIAGENTIC_AUTO_UPDATE_ENABLED"
    os.environ[env_var] = str(enabled).lower()
    return {"ok": True, "auto_update_enabled": enabled, "env": env_var}


def refresh_harness_config(project_root: Path) -> dict[str, Any]:
    """Regenerate harness config and return runtime sync instructions."""
    refreshed = refresh_harness_config_if_installed(project_root, reason="mcp-refresh-tool")
    return {
        "ok": refreshed,
        "refreshed": refreshed,
        "sync": build_runtime_sync(reason="mcp-refresh-tool"),
    }


def diagnose_mcp_servers(project_root: Path, *, timeout: float = 5.0) -> dict[str, Any]:
    """Preflight-probe every configured MCP server for the active harness.

    Spawns each configured server and completes the MCP ``initialize``
    handshake directly (see foundation.mcp.diagnostics) -- this does not
    instrument a live harness session (AUDiaGentic never holds that
    connection), it answers whether each configured server would start right
    now, with how long it took and why if it didn't.
    """
    from audiagentic.foundation.mcp.diagnostics import probe_mcp_server
    from audiagentic.runtime.harness import mcp_config_path, read_mcp_config

    entries = read_mcp_config(mcp_config_path(project_root))
    results = []
    for name, entry in sorted(entries.items()):
        if entry.is_remote:
            continue
        command = [entry.command, *entry.args]
        env = {**os.environ, **entry.env} if entry.env else None
        results.append(
            probe_mcp_server(name, command, cwd=project_root, env=env, timeout=timeout)
        )
    return {"results": results}


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
