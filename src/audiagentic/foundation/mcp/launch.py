"""Launch helpers for component MCP servers."""

from __future__ import annotations

import sys
import sysconfig
from pathlib import Path


def mcp_interpreter() -> str:
    """Return the interpreter that should launch component MCP servers.

    Returns ``sys.executable`` (python.exe on Windows, python3/python on POSIX).
    stdio-based MCP transports require a live stdout — pythonw.exe suppresses
    all output including stdout, which silently breaks MCP connectivity when the
    host (e.g. Claude Code) spawns servers via stdio. The minor UX cost of a
    transient console window on Windows is not worth breaking the transport.
    """
    return str(sys.executable)


def component_mcp_launch(
    module: str,
    *,
    extra_args: tuple[str, ...] = (),
) -> tuple[str, str, tuple[str, ...]]:
    """Return (command, subcommand, args) for launching a component MCP server.

    The canonical launch sequence is::

        <sys.executable> -m audiagentic.launcher mcp <module> [extra_args...]

    invoking the launcher module directly rather than the ``audiagentic``
    console-script stub. The live interpreter preserves the stdio transport.

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
    Consumers compose the full argv as ``[command, subcommand, *args]``.
    """
    return (mcp_interpreter(), "-m", ("audiagentic.launcher", "mcp", module, *extra_args))


def cli_entrypoint() -> str:
    """Absolute path of the ``audiagentic`` console script of this installation.

    User-scope registrations launch servers through the CLI entrypoint, never an
    interpreter path, and name this installation's script explicitly so another
    ``audiagentic`` earlier on PATH cannot serve them.
    """
    from audiagentic.foundation.contracts.errors import make_error_factory

    name = "audiagentic.exe" if sys.platform == "win32" else "audiagentic"
    script = Path(sysconfig.get_path("scripts")) / name
    if not script.is_file():
        raise make_error_factory("CFG", "MCPLAUNCH", "foundation")(
            1, "This installation has no audiagentic console script", path=str(script)
        )
    return str(script)
