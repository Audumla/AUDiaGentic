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

from audiagentic.provisioning.release_please.install import (
    SUPPORTED_RELEASE_TYPES,
    install,
)
from audiagentic.provisioning.release_please.manage import status, update_workflow


def _project_root() -> Path:
    repo_root = os.environ.get("AUDIAGENTIC_REPO_ROOT")
    if not repo_root:
        raise RuntimeError("AUDIAGENTIC_REPO_ROOT not set")
    return Path(repo_root)


def build_server() -> FastMCP:
    mcp = FastMCP(
        "audiagentic-release-please",
        instructions=(
            "Manages release-please installation for the target project. "
            "Use release_please_status to inspect current state before acting. "
            "Use install_release_please to set up a new project. "
            "Use update_release_please_workflow to refresh the workflow from the "
            "current template without touching config or manifest."
        ),
    )

    @mcp.tool(description=(
        "Return the release-please installation status for the target project. "
        "Reports which files are present, the current version, and release type."
    ))
    def release_please_status() -> dict[str, Any]:
        return status(_project_root())

    @mcp.tool(description=(
        "Install release-please into the target project. "
        "Writes release-please-config.json, .release-please-manifest.json, and "
        ".github/workflows/release.yml. Skips files that already exist. "
        f"Supported release_type values: {SUPPORTED_RELEASE_TYPES}."
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

    @mcp.tool(description=(
        "Re-render the release workflow from the current audiagentic template. "
        "Preserves release-please-config.json and .release-please-manifest.json untouched. "
        "Use this to pull in template improvements without reinstalling."
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
