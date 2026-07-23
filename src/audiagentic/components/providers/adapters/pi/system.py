"""Pi-adapter-internal system resolution.

Owns the pi-specific "where is my system install" knowledge — no other
adapter or the runtime-orchestration layer needs these. Resolves the system
CLI itself (never an embedded copy) via ``shutil.which``.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from audiagentic.components.providers.services.system_probe import (
    resolve_system_package_root,
)


def resolve_system_pi_coding_agent() -> Path | None:
    """The system-installed ``@earendil-works/pi-coding-agent`` package dir.

    Used to read version metadata and bundled assets (themes) from the same
    system install the CLI comes from, instead of an embedded copy.
    """
    cli = shutil.which("pi")
    if not cli:
        return None
    root = resolve_system_package_root(cli)
    if root is None:
        return None
    pkg = root / "@earendil-works" / "pi-coding-agent"
    return pkg if pkg.is_dir() else None


def resolve_system_pi_executable() -> str | None:
    """Resolve the system Pi CLI without borrowing runtime orchestration."""
    return shutil.which("pi")


def resolve_system_pi_package(package_name: str) -> Path | None:
    """Resolve one package beside the system Pi installation."""
    cli = resolve_system_pi_executable()
    if not cli:
        return None
    root = resolve_system_package_root(cli)
    if root is None:
        return None
    package = root / package_name
    return package if package.is_dir() else None


def resolve_system_pi_mcp_adapter() -> Path | None:
    """The system-installed ``pi-mcp-adapter`` package dir, if present."""
    cli = shutil.which("pi")
    if not cli:
        return None
    root = resolve_system_package_root(cli)
    if root is None:
        return None
    pkg = root / "pi-mcp-adapter"
    return pkg if pkg.is_dir() else None


def resolve_system_pi_acp_argv(version: str | None = None) -> list[str] | None:
    """Argv prefix to launch the pi-acp bridge from the system, or None.

    Prefers a ``pi-acp`` executable on PATH; otherwise falls back to ``npx``
    (which resolves/caches the package), matching how pi-acp is invoked
    system-side. Never resolves an embedded copy.
    """
    direct = shutil.which("pi-acp")
    if direct:
        return [direct]
    npx = shutil.which("npx")
    if npx:
        return [npx, "--yes", f"pi-acp@{version}" if version else "pi-acp"]
    return None


__all__ = [
    "resolve_system_pi_acp_argv",
    "resolve_system_pi_coding_agent",
    "resolve_system_pi_executable",
    "resolve_system_pi_mcp_adapter",
    "resolve_system_pi_package",
]
