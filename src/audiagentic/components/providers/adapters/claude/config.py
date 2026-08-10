"""Claude provider config path resolution."""

from __future__ import annotations

from pathlib import Path


def resolve_claude_mcp_config_path(project_root: Path | None) -> Path:
    """Resolve Claude's MCP config path.

    Returns the project-local .mcp.json file. Claude Code supports three
    scopes (local/project/user) and project scope (.mcp.json at project root)
    is the correct path for per-project MCP server management.
    """
    if project_root is None:
        return Path.home() / ".claude" / "mcp.json"
    return project_root / ".mcp.json"
