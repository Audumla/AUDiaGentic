"""Release-please MCP server — release management tools."""
from __future__ import annotations

from audiagentic.components.release import release_api
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


@mcp.tool()
@log_tool_call
def dispatch_release_workflow(
    owner: str | None = None,
    repo: str | None = None,
    release_id: str = "rel_0003",
    ref: str = "main",
    interactive: bool = True,
) -> dict:
    """Trigger the Release workflow dispatch on GitHub.

    Opens browser for GitHub OAuth if no token is stored.
    """
    return release_api.dispatch_release_workflow(owner, repo, release_id, ref, interactive)


@mcp.tool()
@log_tool_call
def github_auth(interactive: bool = True) -> dict:
    """Start GitHub OAuth (device flow) or report current auth status.

    Non-blocking. If already authenticated (env/stored token) returns status.
    Otherwise returns a user-code and verification URI to show the user, plus a
    device-code to pass to github_auth_poll. Show the user-code/URI to the user,
    then call github_auth_poll until it reports authenticated.
    """
    return release_api.github_auth(interactive)


@mcp.tool()
@log_tool_call
def github_auth_poll(device_code: str) -> dict:
    """Poll once for completion of a device flow started by github_auth.

    Pass the device-code returned by github_auth. Returns status 'pending' or
    'slow_down' while waiting, or the authenticated status once granted. Wait
    the reported 'interval' seconds between polls.
    """
    return release_api.github_auth_poll(device_code)


@mcp.tool()
@log_tool_call
def clear_github_auth() -> dict:
    """Remove stored GitHub token."""
    return release_api.clear_github_auth()


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("release-please")
    mcp.run()


if __name__ == "__main__":
    main()
