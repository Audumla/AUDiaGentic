"""Release-please MCP server — release management tools."""
from __future__ import annotations

from audiagentic.components.release import release_api
from audiagentic.foundation.lifecycle.components import DEFAULT_VERSION
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def install_release_please(
    release_type: str = "python",
    branch: str = "main",
    python_version: str = "3.13",
    initial_version: str = DEFAULT_VERSION,
) -> dict:
    return release_api.install(project_root_from_env(), release_type, branch, python_version, initial_version)


@mcp.tool()
@log_tool_call
def update_release_please_workflow(branch: str = "main", python_version: str = "3.13") -> dict:
    return release_api.update_workflow(project_root_from_env(), branch, python_version)


@mcp.tool()
@log_tool_call
def finalize_release(release_id: str = "rel_0001") -> dict:
    return release_api.finalize(project_root_from_env(), release_id)


@mcp.tool()
@log_tool_call
def dispatch_release_workflow(
    owner: str | None = None,
    repo: str | None = None,
    release_id: str = "rel_0003",
    ref: str = "main",
    interactive: bool = True,
) -> dict:
    return release_api.dispatch_release_workflow(owner, repo, release_id, ref, interactive)


@mcp.tool()
@log_tool_call
def github_auth(interactive: bool = True) -> dict:
    return release_api.github_auth(interactive)


@mcp.tool()
@log_tool_call
def github_auth_poll(device_code: str) -> dict:
    return release_api.github_auth_poll(device_code)


@mcp.tool()
@log_tool_call
def clear_github_auth() -> dict:
    return release_api.clear_github_auth()


@mcp.tool()
@log_tool_call
def build_release_artifacts(
    release_id: str = "rel_0003",
    tag: bool = True,
    pypi: bool = False,
    github_release: bool = False,
    interactive: bool = True,
) -> dict:
    return release_api.build_release_artifacts(
        release_id=release_id,
        tag=tag,
        pypi=pypi,
        github_release=github_release,
        interactive=interactive,
    )


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("release-please")
    mcp.run()


if __name__ == "__main__":
    main()
