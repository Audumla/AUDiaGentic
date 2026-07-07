from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from audiagentic.runtime.system.platform import platform_key


def tool_available(name: str) -> bool:
    """Return True if the named executable is on PATH."""
    return shutil.which(name) is not None


def uv_available() -> bool:
    """Return True if the uv toolchain (uv or uvx) is installed.

    Adds a ``~/.local/bin`` fallback because uv's installer drops binaries
    there, which is not always on PATH for the running process.
    """
    if tool_available("uvx") or tool_available("uv"):
        return True
    local_bin = Path.home() / ".local" / "bin"
    return (local_bin / "uv").exists() or (local_bin / "uvx").exists()


def privilege_prefix() -> tuple[str, ...]:
    """Return ('sudo',) when not running as root, empty tuple otherwise.

    Used by system package manager recipes (apt, dnf, pacman) so the same
    recipe works both on normal user accounts and inside Docker containers
    where the process already runs as root and sudo is absent.
    """
    if sys.platform.startswith("win"):
        return ()
    getuid = getattr(os, "getuid", None)
    if getuid is None or getuid() == 0:
        return ()
    return ("sudo",)


PLATFORM_PM_MAP: dict[str, tuple[str, ...]] = {
    "win": ("winget", "scoop", "choco"),
    "darwin": ("brew",),
    "linux": ("apt", "dnf", "pacman"),
}


def detect_pkg_manager() -> str | None:
    """Return the first supported package manager found on the current platform."""
    platform = platform_key()
    for pm in PLATFORM_PM_MAP.get(platform, ()):
        if tool_available(pm):
            return pm
    return None


def platform_allowed(constraints: tuple[str, ...] | list[str]) -> bool:
    """Check the current platform against a canonical constraint list.

    Constraints must use canonical platform keys: ``darwin``, ``linux``,
    ``win`` (matching :func:`platform_key`). Unknown keys never match and are
    logged as data errors — fix the config rather than aliasing here. An
    empty constraint list means all platforms are allowed.
    """
    if not constraints:
        return True
    valid = set(PLATFORM_PM_MAP)
    unknown = [c for c in constraints if c not in valid]
    if unknown:
        import logging

        logging.getLogger(__name__).warning(
            "unknown platform constraint keys %s (valid: %s)", unknown, sorted(valid)
        )
    return platform_key() in set(constraints)
