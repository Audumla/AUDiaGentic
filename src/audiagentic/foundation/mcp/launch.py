"""Launch helpers for component MCP servers."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def mcp_interpreter() -> str:
    """Return the interpreter that should launch component MCP servers.

    Prefers the windowless ``pythonw.exe`` sibling of the running interpreter on
    Windows so each stdio server starts without allocating a console — no
    ``conhost.exe`` and no flashing console window per server (stdio pipes are
    inherited regardless of subsystem, so the MCP transport is unaffected).
    Falls back to ``sys.executable`` when pythonw is absent (every POSIX case,
    and unusual Windows layouts).

    Using the interpreter directly also drops the ``audiagentic.exe``
    console-script stub from the process chain (stub -> venv python -> base
    python becomes venv pythonw -> base python).
    """
    exe = Path(sys.executable)
    if os.name == "nt":
        windowless = exe.with_name("pythonw.exe")
        if windowless.exists():
            return str(windowless)
    return str(exe)


def component_mcp_launch(
    module: str,
    *,
    extra_args: tuple[str, ...] = (),
) -> tuple[str, str, tuple[str, ...]]:
    """Return (command, subcommand, args) for launching a component MCP server.

    The canonical launch sequence is::

        <pythonw> -m audiagentic.launcher mcp <module> [extra_args...]

    invoking the launcher module directly rather than the ``audiagentic``
    console-script stub. See :func:`mcp_interpreter` for why the windowless
    interpreter is used.

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
