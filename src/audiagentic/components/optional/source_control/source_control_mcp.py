"""Source control MCP server — component management and configuration."""
from __future__ import annotations

try:
    from mcp.server.fastmcp.server import Context
except ImportError:  # pragma: no cover
    Context = None  # type: ignore[assignment, misc]

from audiagentic.components.optional.source_control import source_control_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    run_blocking_with_output,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def get_source_control_status() -> dict:
    """Return availability of git, gh CLI, and official MCP servers."""
    return source_control_api.get_source_control_status()


@mcp.tool()
@log_tool_call
async def install_dependencies(names: list[str], ctx: Context = None) -> dict:
    """Install source-control dependencies (git, gh, gh-mcp, uv) via host package manager.

    Call only after user confirms which dependencies to install. Use detect_missing in
    get_source_control_status to discover which are absent.
    """
    return await source_control_api.install_dependencies(
        names,
        ctx=ctx,
        run_with_output=run_blocking_with_output,
    )


@mcp.tool()
@log_tool_call
async def uninstall_dependencies(names: list[str], ctx: Context = None) -> dict:
    """Uninstall source-control dependencies via host package manager.

    Explicit user-requested action only — does NOT run when the component is uninstalled.
    """
    return await source_control_api.uninstall_dependencies(
        names,
        ctx=ctx,
        run_with_output=run_blocking_with_output,
    )


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("source-control")
    mcp.run()


if __name__ == "__main__":
    main()
