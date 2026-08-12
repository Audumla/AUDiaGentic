"""Privileged Agents administration MCP boundary placeholder."""
from __future__ import annotations

from audiagentic.foundation.mcp.component_server import mcp_server, run_mcp_server

mcp = mcp_server(__name__)


def main() -> None:
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
