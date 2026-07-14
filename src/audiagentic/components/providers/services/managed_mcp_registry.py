"""Track AUDiaGentic-owned provider MCP entries by stable managed id."""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.toolchains.managed_config import ManagedFragmentRegistry


def mcp_ownership_registry(project_root: Path) -> ManagedFragmentRegistry:
    """The one MCP-scoped instance of the foundation ManagedFragmentRegistry."""
    return ManagedFragmentRegistry(
        project_root,
        "managed-mcp-servers.json",
        top_level_key="providers",
    )


def _registry_path(project_root: Path) -> Path:
    return mcp_ownership_registry(project_root).path


def load_managed_mcp_registry(project_root: Path) -> dict[str, dict[str, str]]:
    return mcp_ownership_registry(project_root).load()


def save_managed_mcp_registry(project_root: Path, registry: dict[str, dict[str, str]]) -> None:
    mcp_ownership_registry(project_root).save(registry)
