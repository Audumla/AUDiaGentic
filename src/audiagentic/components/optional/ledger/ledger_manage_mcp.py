"""Ledger manage MCP server — component health and installation state."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.components.optional.ledger import ledger_api
from audiagentic.foundation.mcp.component_server import log_tool_call, mcp_server

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
@log_tool_call
def get_ledger_status() -> dict:
    """Return ledger installation state, fragment count, and last sync time."""
    return ledger_api.get_status(_project_root())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("ledger-manage")
    mcp.run()


if __name__ == "__main__":
    main()
