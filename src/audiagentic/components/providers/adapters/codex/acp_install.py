"""Shared installation and resolution for the Codex ACP bridge.

The bridge is an npm package, but it is not the Codex CLI itself.  Keep its
installation in one AUDiaGentic-managed, user-global provider directory so
every project launches the same pinned bridge without invoking ``npx`` for
each request.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from audiagentic.foundation.paths.home import global_provider_runtime

CODEX_ACP_PACKAGE = "@agentclientprotocol/codex-acp"
CODEX_ACP_VERSION = "1.6.2"


def shared_codex_acp_root() -> Path:
    """Return the versioned, user-global install prefix for codex-acp."""

    return global_provider_runtime("codex") / "acp" / CODEX_ACP_VERSION


def shared_codex_acp_entrypoint() -> Path | None:
    """Return the installed bridge entrypoint, if the shared install exists."""

    entrypoint = (
        shared_codex_acp_root()
        / "node_modules"
        / "@agentclientprotocol"
        / "codex-acp"
        / "dist"
        / "index.js"
    )
    return entrypoint if entrypoint.is_file() else None


def shared_codex_acp_node_launch() -> tuple[str, tuple[str, ...]] | None:
    """Return ``(node, (entrypoint,))`` for the shared bridge, when usable."""

    entrypoint = shared_codex_acp_entrypoint()
    node = shutil.which("node")
    if entrypoint is None or node is None:
        return None
    return node, (str(entrypoint),)


def codex_acp_recipe_path() -> Path:
    """Return the packaged declarative recipe used by the installer."""

    from audiagentic.foundation.paths.names import get_package_config_dir

    return get_package_config_dir() / "recipes" / "codex-acp-bridge.yaml"


def install_shared_codex_acp(*, dry_run: bool = False) -> Any:
    """Install (or verify) the pinned bridge in the shared provider prefix.

    ``dry_run`` only materializes the recipe plan.  No launch path calls this
    helper implicitly; provisioning remains an explicit lifecycle operation.
    """

    from audiagentic.foundation.toolchains.recipe_execution import execute_recipe_mode

    prefix = shared_codex_acp_root()
    if not dry_run:
        prefix.mkdir(parents=True, exist_ok=True)
    params = {
        "PREFIX": str(prefix),
        "PACKAGE": CODEX_ACP_PACKAGE,
        "VERSION": CODEX_ACP_VERSION,
    }
    return execute_recipe_mode(
        codex_acp_recipe_path(),
        params,
        "plan" if dry_run else "apply",
        context={"provider_id": "codex", "prefix": str(prefix)},
    )


__all__ = [
    "CODEX_ACP_PACKAGE",
    "CODEX_ACP_VERSION",
    "codex_acp_recipe_path",
    "install_shared_codex_acp",
    "shared_codex_acp_entrypoint",
    "shared_codex_acp_node_launch",
    "shared_codex_acp_root",
]
