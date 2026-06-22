"""Launch helpers for component MCP servers."""
from __future__ import annotations


def component_mcp_launch(
    module: str,
    *,
    extra_args: tuple[str, ...] = (),
) -> tuple[str, str, tuple[str, ...]]:
    """Return (command, subcommand, args) for launching a component MCP server.

    The canonical launch sequence is::

        audiagentic mcp <module> [extra_args...]

    Parameters
    ----------
    module:
        Fully-qualified module name of the MCP server (e.g.
        ``audiagentic.components.project.project_mcp``).
    extra_args:
        Additional CLI arguments passed to the server module.

    Returns
    -------
    A 3-tuple of (command, subcommand, args) suitable for subprocess invocation.
    """
    return ("audiagentic", "mcp", (module, *extra_args))
