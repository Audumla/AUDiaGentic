"""Memory component management MCP server."""
from __future__ import annotations

import logging
from typing import Any

from audiagentic.components.memory import memory_api
from audiagentic.foundation.mcp.component_server import (
    FastMCP,
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
)

logger = logging.getLogger(__name__)


def build_server() -> FastMCP:
    mcp = mcp_server(__name__)

    @mcp.tool()
    @log_tool_call
    def memory_status() -> dict[str, Any]:
        return memory_api.memory_status(project_root_from_env()).to_dict()

    @mcp.tool()
    @log_tool_call
    def memory_hindsight_status() -> dict[str, Any]:
        """Return per-provider Hindsight integration status.

        Shows state (active/inactive/not_registered), source verification,
        and owned artifacts for each provider's Hindsight recipe.
        """
        return memory_api.memory_hindsight_status(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def memory_list_implementations() -> dict[str, Any]:
        return memory_api.memory_list_implementations(project_root_from_env())

    @mcp.tool()
    @log_tool_call
    def memory_select_implementation(implementation_id: str) -> dict[str, Any]:
        """Switch the active memory implementation. Provider integration reconciles asynchronously."""
        root = project_root_from_env()
        result = memory_api.memory_select_implementation(root, implementation_id)
        result["note"] = "Provider integrations reconcile asynchronously via observer"
        return result

    @mcp.tool()
    @log_tool_call
    def memory_get_config(implementation_id: str | None = None) -> dict[str, Any]:
        """Return resolved config plus the settable-option schema for an implementation.

        The ``schema`` field describes every option the implementation accepts
        (type, description, required, default, allowed values) — use it to
        discover what can be set, then pass any of those keys to
        ``memory_set_config``. Memory has no implementation-specific tools;
        all configuration goes through this generic get/set pair.
        """
        return memory_api.memory_get_config(project_root_from_env(), implementation_id)

    @mcp.tool()
    @log_tool_call
    def memory_set_config(
        implementation_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate and persist config updates for a memory implementation.

        Provider integrations reconcile asynchronously via observer.
        """
        root = project_root_from_env()
        result = memory_api.memory_set_config(root, implementation_id, updates)
        result["note"] = "Provider integrations reconcile asynchronously via observer"
        return result

    return mcp


def main() -> int:
    run_mcp_server(build_server(), "memory-mgmt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
