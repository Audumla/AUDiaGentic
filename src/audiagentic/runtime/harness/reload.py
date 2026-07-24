"""Harness-generic runtime reload marker protocol.

Both pi and opencode write the same reload-request.json structure so that
session monitors can detect config changes without harness-specific logic.
"""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.foundation.time import now_iso_z

_ALWAYS_RELOAD = {"manual-refresh", "mcp-refresh-tool"}
_MCP_RELOAD = {"component-installed", "component-uninstalled", "component-enabled", "component-disabled"}


def _runtime_action_for_reason(reason: str, *, has_mcp_servers: bool = True) -> str:
    if reason in _ALWAYS_RELOAD:
        return "reload_required"
    if reason in _MCP_RELOAD:
        return "reload_required" if has_mcp_servers else "refresh_required"
    return "refresh_required"


def runtime_reload_request_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "harness" / "reload-request.json"


def build_runtime_sync(
    *,
    reason: str,
    component_id: str | None = None,
    target: str,
    has_mcp_servers: bool = True,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "target": target,
        "action": _runtime_action_for_reason(reason, has_mcp_servers=has_mcp_servers),
        "reason": reason,
    }
    if component_id:
        payload["component_id"] = component_id
    return payload


def write_reload_marker(
    project_root: Path,
    *,
    reason: str,
    component_id: str | None = None,
    target: str,
    has_mcp_servers: bool = True,
) -> Path:
    path = runtime_reload_request_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "requested_at": now_iso_z(),
        **build_runtime_sync(reason=reason, component_id=component_id, target=target, has_mcp_servers=has_mcp_servers),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
