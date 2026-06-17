"""Public API surface for the core session component."""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any

from audiagentic.runtime.harness import build_runtime_sync, refresh_harness_config_if_installed

from . import session_embedded_rig, session_runtime_status, session_visibility


def status(project_root: Path) -> dict[str, Any]:
    """Return current harness/session status."""
    return {
        "versions": session_runtime_status.versions(),
        "model": session_runtime_status.model_info(),
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


def cli_visibility(project_root: Path) -> dict[str, bool]:
    """Return effective CLI visibility state."""
    return session_visibility.effective_cli_visibility(project_root)


def set_cli_visibility(
    project_root: Path,
    *,
    show_thinking_blocks: bool | None,
    show_tool_blocks: bool | None,
    scope: str,
) -> dict[str, Any]:
    """Update CLI visibility config and request runtime reload."""
    return session_visibility.set_cli_visibility(
        project_root=project_root,
        show_thinking_blocks=show_thinking_blocks,
        show_tool_blocks=show_tool_blocks,
        scope=scope,
    )


def refresh_harness_config(project_root: Path) -> dict[str, Any]:
    """Regenerate harness config and return runtime sync instructions."""
    refreshed = refresh_harness_config_if_installed(project_root, reason="mcp-refresh-tool")
    return {
        "ok": refreshed,
        "refreshed": refreshed,
        "sync": build_runtime_sync(reason="mcp-refresh-tool"),
    }


async def update_embedded_rig(*, ctx, run_with_output) -> dict[str, Any]:
    """Update embedded rig binaries and restart active rig when needed."""
    return await session_embedded_rig.update_embedded_rig(ctx=ctx, run_with_output=run_with_output)


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
