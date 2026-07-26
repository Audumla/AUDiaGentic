"""Runtime sync advisory metadata (HA05).

build_runtime_sync + _runtime_action_for_reason are pure functions that
classify a reason string into an action (refresh_required/reload_required)
and shape a dict. This is returned synchronously inside MCP tool responses
so the calling agent can see and act on it in the same turn.

HA05: the file-writing half (write_reload_marker / runtime_reload_request_path)
was deleted — its sole reader was Pi's footer.ts extension (deleted HA04),
and OpenCode never had a consumer either.
"""
from __future__ import annotations

_ALWAYS_RELOAD = {"manual-refresh", "mcp-refresh-tool"}
_MCP_RELOAD = {"component-installed", "component-uninstalled", "component-enabled", "component-disabled"}


def _runtime_action_for_reason(reason: str, *, has_mcp_servers: bool = True) -> str:
    if reason in _ALWAYS_RELOAD:
        return "reload_required"
    if reason in _MCP_RELOAD:
        return "reload_required" if has_mcp_servers else "refresh_required"
    return "refresh_required"


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
