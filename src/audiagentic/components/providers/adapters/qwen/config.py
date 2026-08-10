"""Qwen provider config path resolution."""

from __future__ import annotations

from pathlib import Path


def resolve_qwen_mcp_config_path(project_root: Path | None) -> Path:
    """Resolve Qwen's MCP config path.

    Returns the project-local .qwen/settings.json file. Qwen Code supports
    both user scope (~/.qwen/settings.json) and project scope
    (.qwen/settings.json at project root); project scope overrides global.
    """
    if project_root is None:
        return Path.home() / ".qwen" / "settings.json"
    return project_root / ".qwen" / "settings.json"
