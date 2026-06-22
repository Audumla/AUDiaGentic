"""Portable CLI probing for provider adapters.

Centralizes the one Windows-specific gotcha that every CLI probe hits: npm/pip
console-script shims (e.g. ``opencode.CMD``) are batch files that
``CreateProcess`` cannot launch from a bare-name argv list, so a plain
``subprocess.run(["opencode", ...])`` raises ``WinError 2`` even though the tool
is installed and on PATH.
"""
from __future__ import annotations

import os
import shutil
import subprocess


def run_cli(command: list[str], timeout: float = 15.0) -> subprocess.CompletedProcess:
    """Run *command* portably for capability probing.

    On Windows, route through the shell so the command interpreter resolves a
    ``.CMD``/``.BAT`` shim via PATHEXT.  On POSIX, exec the argv list directly to
    avoid shell-quoting pitfalls.

    ``stdin`` is always detached (DEVNULL): a version probe never needs input, and
    when the caller is an MCP stdio server the parent's stdin is the live JSON-RPC
    pipe — a probed CLI that reads stdin would otherwise block until timeout.
    """
    if os.name == "nt":
        return subprocess.run(
            subprocess.list2cmdline(command),
            shell=True, check=False, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    return subprocess.run(
        command, check=False, capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def probe_cli_version(executable_name: str, command: list[str], timeout: float = 15.0) -> dict:
    """Standard version-style CLI probe returning the provider probe dict.

    Resolves *executable_name* on PATH, runs *command*, and reports availability
    from a zero exit code.  A missing executable or any spawn failure reports
    ``available: False`` — never masks a failure as available.
    """
    executable = shutil.which(executable_name)
    if executable is None:
        return {
            "available": False,
            "command": command,
            "executable": None,
            "returncode": None,
            "stdout": "",
            "stderr": "command not found",
        }
    try:
        completed = run_cli(command, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "command": command,
            "executable": executable,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "available": completed.returncode == 0,
        "command": command,
        "executable": executable,
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }
