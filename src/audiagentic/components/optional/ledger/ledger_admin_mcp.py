"""Ledger admin MCP server — management and CLI tools for the ledger component."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.components.optional.ledger import api
from audiagentic.foundation.mcp.component_server import log_tool_call, mcp_server

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
@log_tool_call
def get_ledger_status() -> dict:
    """Return ledger installation state, fragment count, and last sync time."""
    return api.get_status(_project_root())


@mcp.tool()
@log_tool_call
def sync_ledger() -> dict:
    """Merge all pending fragments into the current release ledger."""
    return api.sync(_project_root())


@mcp.tool()
@log_tool_call
def get_audit_report() -> dict:
    """Regenerate and return paths to the audit summary and check-in docs."""
    return api.generate_audit(_project_root())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("ledger-admin")
    mcp.run()


if __name__ == "__main__":
    main()
