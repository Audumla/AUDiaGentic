"""AUDiaGentic release-please MCP server.

Exposes install and management of release-please into a target project.
Reads AUDIAGENTIC_REPO_ROOT from env to locate the target project.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.components.registry import get_mcp_server_declaration

from audiagentic.components.optional.release_please.install import (
    SUPPORTED_RELEASE_TYPES,
    install,
)
from audiagentic.components.optional.release_please.manage import status, update_workflow

register_all_components()


def _project_root() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if not repo_root:
        raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set")
    return Path(repo_root)


def _server_decl():
    return get_mcp_server_declaration("agent-ledger", "audiagentic-release-please")


def _server_instructions() -> str:
    decl = _server_decl()
    return (
        decl.instructions
        if decl and decl.instructions
        else (
            "Manages release-please installation for the target project. "
            "Use release_please_status to inspect current state before acting. "
            "Use install_release_please to set up a new project. "
            "Use update_release_please_workflow to refresh the workflow from the "
            "current template without touching config or manifest."
        )
    )


def _tool_description(name: str, fallback: str) -> str:
    decl = _server_decl()
    if decl and name in decl.tool_descriptions:
        return decl.tool_descriptions[name]
    return fallback


def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-release-please",
        instructions=_server_instructions(),
    )

    @mcp.tool(description=_tool_description(
        "release_please_status",
        "Return the release-please installation status for the target project.",
    ))
    def release_please_status() -> dict[str, Any]:
        return status(_project_root())

    @mcp.tool(description=(
        _tool_description("install_release_please", "Install release-please into the target project.")
        + f" Supported release_type values: {SUPPORTED_RELEASE_TYPES}."
    ))
    def install_release_please(
        release_type: str = "python",
        branch: str = "main",
        python_version: str = "3.13",
        initial_version: str = "0.1.0",
    ) -> dict[str, Any]:
        return install(
            _project_root(),
            release_type=release_type,
            branch=branch,
            python_version=python_version,
            initial_version=initial_version,
        )

    @mcp.tool(description=_tool_description(
        "update_release_please_workflow",
        "Re-render the release workflow from the current audiagentic template.",
    ))
    def update_release_please_workflow(
        branch: str = "main",
        python_version: str = "3.13",
    ) -> dict[str, Any]:
        return update_workflow(
            _project_root(),
            branch=branch,
            python_version=python_version,
        )

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
