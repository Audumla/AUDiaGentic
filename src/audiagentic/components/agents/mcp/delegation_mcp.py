"""Narrow provider-facing child Work delegation surface."""
from __future__ import annotations

from typing import Any

from audiagentic.components.agents.gateway.client import get_gateway_client
from audiagentic.foundation.mcp.component_server import (
    mcp_server,
    project_root_from_env,
    run_mcp_server,
    tool_boundary,
)

mcp = mcp_server(__name__)


@mcp.tool()
@tool_boundary
def agent_work_status(work_id: str) -> dict[str, Any]:
    root = project_root_from_env()
    return get_gateway_client(root).get_agent_work(root, work_id)


def main() -> None:
    run_mcp_server(mcp)


if __name__ == "__main__":
    main()
