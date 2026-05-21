"""Release-please MCP server — release management tools."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.components.optional.release import api
from audiagentic.runtime.mcp.server import mcp_server

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
def release_please_status() -> dict:
    """Return release-please installation status and workflow state."""
    return api.get_status(_project_root())


@mcp.tool()
def install_release_please(
    release_type: str = "python",
    branch: str = "main",
    python_version: str = "3.13",
    initial_version: str = "0.1.0",
) -> dict:
    """Install release-please into the target project."""
    return api.install(_project_root(), release_type, branch, python_version, initial_version)


@mcp.tool()
def update_release_please_workflow(branch: str = "main", python_version: str = "3.13") -> dict:
    """Re-render the release workflow from the current template."""
    return api.update_workflow(_project_root(), branch, python_version)


@mcp.tool()
def finalize_release(release_id: str = "rel_0001") -> dict:
    """Archive current ledger and render release documents (CHANGELOG.md etc)."""
    return api.finalize(_project_root(), release_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
