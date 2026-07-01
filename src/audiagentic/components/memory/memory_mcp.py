"""Memory component management MCP server."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.memory import memory_api
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.mcp.component_server import (
    FastMCP,
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
)

logger = logging.getLogger(__name__)

register_all_components()


def _summarize_recipe_refresh(refresh: dict[str, Any]) -> dict[str, Any]:
    """Build a human-readable summary of the per-provider recipe reconcile.

    Turns the nested reconcile payload into flat counts + failure lines so the
    CLI can show plainly which provider integrations ran, succeeded, or failed.
    """
    providers = (refresh.get("memory") or {}).get("providers") or {}
    applied_ok: list[str] = []
    applied_failed: list[str] = []
    pruned: list[str] = []
    for pid, info in providers.items():
        if info.get("role") == "pruned-stale":
            pruned.append(pid)
        elif info.get("success"):
            applied_ok.append(pid)
        else:
            applied_failed.append(pid)

    parts = [f"Hindsight integration: {len(applied_ok)} ok"]
    if applied_failed:
        parts.append(f"{len(applied_failed)} failed ({', '.join(sorted(applied_failed))})")
    if pruned:
        parts.append(f"{len(pruned)} stale pruned ({', '.join(sorted(pruned))})")
    return {
        "message": "; ".join(parts),
        "applied_ok": sorted(applied_ok),
        "applied_failed": sorted(applied_failed),
        "pruned_stale": sorted(pruned),
    }


def _refresh_provider_recipes(project_root: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Consume the api's provider-recipe-refresh hint via the composition bridge.

    Memory core stays provider-agnostic; the runtime bridge maps the active
    implementation onto enabled providers. Best-effort — never fails the tool.
    """
    if not result.get("needs_provider_recipe_refresh"):
        return result
    try:
        from audiagentic.runtime.lifecycle.provider_recipes import refresh_provider_recipes
        refresh = refresh_provider_recipes(project_root)
        result["provider_recipe_refresh"] = refresh
        result["provider_integration_summary"] = _summarize_recipe_refresh(refresh)
    except Exception:  # noqa: BLE001
        logger.warning("provider recipe refresh failed (non-fatal)", exc_info=True)
    return result


def build_server() -> FastMCP:
    mcp = mcp_server(__name__)

    @mcp.tool()
    @log_tool_call
    def memory_status() -> dict[str, Any]:
        return memory_api.memory_status(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def memory_list_implementations() -> dict[str, Any]:
        return memory_api.memory_list_implementations(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def memory_select_implementation(implementation_id: str) -> dict[str, Any]:
        root = project_root_from_env()
        result = memory_api.memory_select_implementation(root, implementation_id)
        return _refresh_provider_recipes(root, result)

    @mcp.tool()
    @log_tool_call
    def memory_get_config(implementation_id: str | None = None) -> dict[str, Any]:
        return memory_api.memory_get_config(project_root_from_env(), implementation_id)

    @mcp.tool()
    @log_tool_call
    def memory_set_config(
        implementation_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        root = project_root_from_env()
        result = memory_api.memory_set_config(root, implementation_id, updates)
        return _refresh_provider_recipes(root, result)

    return mcp


def main() -> int:
    run_mcp_server(build_server(), "memory-mgmt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
