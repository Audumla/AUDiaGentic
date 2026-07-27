"""Ledger MCP server — tools for recording change events and managing ledger content."""
from __future__ import annotations

from audiagentic.components.ledger import ledger_api
from audiagentic.foundation.mcp.component_server import (
    log_tool_call,
    mcp_server,
    project_root_from_env,
)

mcp = mcp_server(__name__)


@mcp.tool()
@log_tool_call
def record_change_event(event: dict | list[dict]) -> dict:
    """Record one or more change event fragments.

    Accepts a single dict or a list of dicts (batch mode — one call,
    one trailing sync). Required per event: change-class, files,
    technical-summary, user-summary-candidate, status ('unreleased').
    Optional: plan-item-ids (array of plan item IDs for automatic linkage).
    """
    project_root = project_root_from_env()
    if isinstance(event, list):
        return ledger_api.record_changes(project_root, event, sync=True)
    return ledger_api.record_change(project_root, event, sync=True)


@mcp.tool()
@log_tool_call
def get_pending_events(group_by: str = "plan-items") -> dict:
    """Return pending (unreleased) events grouped for commit decisions.

    group_by: "plan-items" (default, cluster by shared plan-item-ids),
    "files" (cluster by file overlap), or "flat" (raw ungrouped list).
    """
    return ledger_api.get_pending_events(project_root_from_env(), group_by)


@mcp.tool()
@log_tool_call
def get_fragment(event_id: str) -> dict:
    """Retrieve a single change event by event-id.

    Looks in the current ledger; returns the full event dict or raises
    if not found.
    """
    return ledger_api.get_fragment(event_id, project_root_from_env())


@mcp.tool()
@log_tool_call
def get_current_summary() -> str:
    return ledger_api.get_current_summary(project_root_from_env())


@mcp.tool()
@log_tool_call
def sync_ledger() -> dict:
    return ledger_api.sync(project_root_from_env())


@mcp.tool()
@log_tool_call
def get_audit_report() -> dict:
    return ledger_api.generate_audit(project_root_from_env())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("ledger")
    mcp.run()


if __name__ == "__main__":
    main()
