"""Ledger manage MCP server — component health and installation state."""
from __future__ import annotations

from audiagentic.components.ledger import ledger_api
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def get_ledger_status() -> dict:
    return ledger_api.get_status(project_root_from_env())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("ledger-manage")
    mcp.run()


if __name__ == "__main__":
    main()
