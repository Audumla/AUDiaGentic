"""Antigravity provider config path resolution."""

from __future__ import annotations

from pathlib import Path


def resolve_antigravity_mcp_config_path(project_root: Path | None) -> Path:
    """Resolve Antigravity's MCP config path.

    Returns the project-local .agents/mcp_config.json file. Antigravity supports
    both global (~/.gemini/config/mcp_config.json) and workspace
    (<project>/.agents/mcp_config.json); workspace scope is correct for
    per-project MCP server management.
    """
    if project_root is None:
        return Path.home() / ".gemini" / "antigravity" / "mcp_config.json"
    return project_root / ".agents" / "mcp_config.json"
