"""Ledger manage MCP server — component health and installation state."""
from __future__ import annotations

from audiagentic.components.optional.ledger import ledger_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def get_ledger_status() -> dict:
    """Return ledger installation state, fragment count, and last sync time."""
    return ledger_api.get_status(project_root_from_env())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("ledger-manage")
    mcp.run()


if __name__ == "__main__":
    main()
