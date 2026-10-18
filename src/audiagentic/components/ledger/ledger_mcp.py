"""Ledger MCP server — tools for recording change events and managing ledger content."""
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
def record_change_event(event: dict | list[dict]) -> dict:
    """Record one event or a batch; each event needs class, files, technical and user summaries, and status=unreleased. Batches sync once; plan-item-ids is optional."""
    project_root = project_root_from_env()
    if isinstance(event, list):
        return ledger_api.record_changes(project_root, event, sync=True)
    return ledger_api.record_change(project_root, event, sync=True)


@mcp.tool()
@tool_boundary
def get_pending_events(group_by: str = "plan-items") -> dict:
    """List unreleased events grouped by plan-items, files, or flat."""
    return ledger_api.get_pending_events(project_root_from_env(), group_by)


@mcp.tool()
@tool_boundary
def get_fragment(event_id: str) -> dict:
    """Return one current-ledger event by event-id."""
    return ledger_api.get_fragment(event_id, project_root_from_env())


@mcp.tool()
@tool_boundary
def get_current_summary() -> str:
    """Return the generated current-release summary."""
    return ledger_api.get_current_summary(project_root_from_env())


@mcp.tool()
@tool_boundary
def sync_ledger() -> dict:
    """Merge pending fragments into the current ledger."""
    return ledger_api.sync(project_root_from_env())


@mcp.tool()
@tool_boundary
def get_audit_report() -> dict:
    """Regenerate and return release audit/check-in document paths."""
    return ledger_api.generate_audit(project_root_from_env())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("ledger")
    mcp.run()


if __name__ == "__main__":
    main()
