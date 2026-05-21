"""Ledger admin MCP server — management and CLI tools for the ledger component."""
from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from audiagentic.components.optional.ledger import api

mcp = FastMCP("audiagentic-ledger-admin")


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
def get_ledger_status() -> dict:
    """Return ledger installation state, fragment count, and last sync time."""
    return api.get_status(_project_root())


@mcp.tool()
def sync_ledger() -> dict:
    """Merge all pending fragments into the current release ledger."""
    return api.sync(_project_root())


@mcp.tool()
def get_audit_report() -> dict:
    """Regenerate and return paths to the audit summary and check-in docs."""
    return api.generate_audit(_project_root())


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
