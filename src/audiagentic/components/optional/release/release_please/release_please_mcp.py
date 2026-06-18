"""Release-please MCP server — release management tools."""
from __future__ import annotations

from audiagentic.components.optional.release import release_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)
from audiagentic.runtime.lifecycle.components import DEFAULT_VERSION

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def install_release_please(
    release_type: str = "python",
    branch: str = "main",
    python_version: str = "3.13",
    initial_version: str = DEFAULT_VERSION,
) -> dict:
    """Install release-please into the target project."""
    return release_api.install(project_root_from_env(), release_type, branch, python_version, initial_version)


@mcp.tool()
@log_tool_call
def update_release_please_workflow(branch: str = "main", python_version: str = "3.13") -> dict:
    """Re-render the release workflow from the current template."""
    return release_api.update_workflow(project_root_from_env(), branch, python_version)


@mcp.tool()
@log_tool_call
def finalize_release(release_id: str = "rel_0001") -> dict:
    """Archive current ledger and render release documents (CHANGELOG.md etc)."""
    return release_api.finalize(project_root_from_env(), release_id)


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("release-please")
    mcp.run()


if __name__ == "__main__":
    main()
