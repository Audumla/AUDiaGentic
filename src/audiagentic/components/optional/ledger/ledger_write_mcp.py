"""Ledger write MCP server — provider-facing tools for recording change events."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.components.optional.ledger import api
from audiagentic.foundation.mcp.component_server import mcp_server

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
def record_change_event(event: dict) -> dict:
    """Record a change event fragment to the ledger and sync."""
    return api.record_change(_project_root(), event)


@mcp.tool()
def get_current_summary() -> str:
    """Return the current release summary markdown."""
    return api.get_current_summary(_project_root())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
