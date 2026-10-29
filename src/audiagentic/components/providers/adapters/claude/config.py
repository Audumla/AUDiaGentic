"""Claude provider config path resolution."""

from __future__ import annotations

import os
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory

_config_error = make_error_factory("VAL", "CLAUDECFG", "providers")


def resolve_claude_mcp_config_path(project_root: Path | None) -> Path:
    """Claude's project scope: ``.mcp.json`` at the project root.

    There is no project-less fallback: Claude's user scope is a different
    file, registered by ``audiagentic setup`` (:func:`resolve_claude_user_config_path`).
    """
    if project_root is None:
        raise _config_error(
            1, "Claude project MCP registration needs a project root; "
            "user-scope registration is 'audiagentic setup harness claude'"
        )
    return project_root / ".mcp.json"


def resolve_claude_user_config_path(_project_root: Path | None = None) -> Path:
    """Claude's user-scope state file, which holds user-scope ``mcpServers``.

    ``$CLAUDE_CONFIG_DIR/.claude.json`` when Claude runs with a config
    directory, else ``~/.claude.json``. It does not depend on any project.
    """
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(config_dir) / ".claude.json" if config_dir else Path.home() / ".claude.json"
