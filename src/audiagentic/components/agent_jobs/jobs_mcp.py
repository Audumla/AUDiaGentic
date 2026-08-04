"""Agent-jobs operational MCP server — read-only event-jobs overview (EDJ14).

Mirrors the gateway_mcp construction: one thin server on the shared
foundation.mcp.component_server primitives, tools resolve the project root
from the environment only.
"""
from __future__ import annotations

from typing import Any

from audiagentic.components.agent_jobs import jobs_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
    run_mcp_server,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def event_jobs_overview_tool() -> dict[str, Any]:
    """Operator-facing summary of event-driven jobs: per-trigger fired/
    suppressed/failed counts, event-origin job counts by state, and the 5
    most recent trigger failures (redacted). Read-only."""
    return jobs_api.event_jobs_overview(project_root_from_env())


def main() -> None:
    run_mcp_server(mcp, "agent-jobs")


if __name__ == "__main__":
    main()
