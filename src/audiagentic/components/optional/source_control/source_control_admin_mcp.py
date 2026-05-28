"""Source control admin MCP server — component management and configuration."""
from __future__ import annotations

import os
from pathlib import Path

try:
    from mcp.server.fastmcp.server import Context
except ImportError:  # pragma: no cover
    Context = None  # type: ignore[assignment, misc]

from audiagentic.components.optional.source_control.bootstrap import (
    SOURCE_CONTROL_DEPENDENCY_IDS,
    detect_availability,
)
from audiagentic.foundation.dependencies import (
    SYSTEM_DEPENDENCIES,
    detect_missing,
    install_system_dependencies,
    uninstall_system_dependencies,
)
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    run_blocking_with_output,
)

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
@log_tool_call
def get_source_control_status() -> dict:
    """Return availability of git, gh CLI, and official MCP servers."""
    missing = detect_missing(SYSTEM_DEPENDENCIES, SOURCE_CONTROL_DEPENDENCY_IDS)
    return {**detect_availability(), "missing-dependencies": missing}


@mcp.tool()
@log_tool_call
async def install_dependencies(names: list[str], ctx: Context = None) -> dict:
    """Install source-control dependencies (git, gh, gh-mcp, uv) via host package manager.

    Call only after user confirms which dependencies to install. Use detect_missing in
    get_source_control_status to discover which are absent.
    """
    return await run_blocking_with_output(
        ctx=ctx,
        logger="source-control.dependencies.install",
        heartbeat_message="Dependency install still running...",
        work=lambda output: install_system_dependencies(names, on_progress=output),
    )


@mcp.tool()
@log_tool_call
async def uninstall_dependencies(names: list[str], ctx: Context = None) -> dict:
    """Uninstall source-control dependencies via host package manager.

    Explicit user-requested action only — does NOT run when the component is uninstalled.
    """
    return await run_blocking_with_output(
        ctx=ctx,
        logger="source-control.dependencies.uninstall",
        heartbeat_message="Dependency uninstall still running...",
        work=lambda output: uninstall_system_dependencies(names, on_progress=output),
    )


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("source-control")
    mcp.run()


if __name__ == "__main__":
    main()
