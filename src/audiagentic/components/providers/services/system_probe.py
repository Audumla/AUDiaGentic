"""Pure derivation helpers for system-installed CLI package layout.

Deliberately decoupled from CLI *discovery* (``shutil.which``-style lookup,
already owned by each adapter via ``require_executable``/``probe.py``): this
module only derives where an npm-installed package's ``node_modules`` sits,
given an already-resolved CLI path. No provider-specific knowledge lives here.
"""
from __future__ import annotations

from pathlib import Path


def resolve_system_package_root(cli_path: str | Path) -> Path | None:
    """The ``node_modules`` dir alongside a resolved CLI binary, if present.

    Derived from the CLI path (``<npm-global>/<bin>`` -> ``<npm-global>/node_modules``).
    Used to load CLI-adjacent packages from the same system install the CLI
    comes from. Best-effort: returns None if the directory doesn't exist.
    """
    cli = Path(cli_path)
    resolved = cli.resolve()
    # POSIX npm bins are symlinks into a scoped package below node_modules.
    # Prefer that authoritative ancestor when present.
    for parent in resolved.parents:
        if parent.name == "node_modules" and parent.is_dir():
            return parent
    # Windows npm shims sit beside their node_modules directory.  Some POSIX
    # prefixes instead use <prefix>/bin plus <prefix>/lib/node_modules.
    candidates = (
        cli.parent / "node_modules",
        cli.parent.parent / "lib" / "node_modules",
    )
    return next((candidate for candidate in candidates if candidate.is_dir()), None)


__all__ = ["resolve_system_package_root"]
