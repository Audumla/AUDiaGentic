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
def record_change_event(event: dict) -> dict:
    """Record a change event fragment to the ledger and sync.

    Required fields: change-class, files, technical-summary,
    user-summary-candidate, status (always 'unreleased').

    change-class: feature, code-fix, refactor, docs, tests, config, release, audit, workflow.
    """
    return ledger_api.record_change(project_root_from_env(), event, sync=True)


@mcp.tool()
@log_tool_call
def get_current_summary() -> str:
    """Return the current release summary markdown."""
    return ledger_api.get_current_summary(project_root_from_env())


@mcp.tool()
@log_tool_call
def sync_ledger() -> dict:
    """Merge all pending fragments into the current release ledger."""
    return ledger_api.sync(project_root_from_env())


@mcp.tool()
@log_tool_call
def get_audit_report() -> dict:
    """Regenerate and return paths to the audit summary and check-in docs."""
    return ledger_api.generate_audit(project_root_from_env())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("ledger")
    mcp.run()


if __name__ == "__main__":
    main()
