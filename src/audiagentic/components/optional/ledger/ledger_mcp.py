"""Ledger MCP server — tools for recording change events and managing ledger content."""
from __future__ import annotations

import os
from pathlib import Path

from audiagentic.components.optional.ledger import ledger_api
from audiagentic.foundation.mcp.component_server import log_tool_call, mcp_server

mcp = mcp_server(__name__)


def _project_root() -> Path:
    return Path(os.environ.get("AUDIAGENTIC_REPO_ROOT", ".")).resolve()


@mcp.tool()
@log_tool_call
def record_change_event(event: dict) -> dict:
    """Record a change event fragment to the ledger and sync.

    Required fields: event-id, timestamp-utc, project-id, source (kind, provider-id, surface, prompt-tag), change-class, files, technical-summary, user-summary-candidate, status (always 'unreleased').

    source.kind: 'interactive-prompt' (most common), 'job-run', 'workflow-stage', 'manual-script', 'release-finalization'.
    source.session-id, job-id, packet-id, review-id: null for ad-hoc work; populated by job/packet/review system for structured workflows.
    change-class: feature, code-fix, refactor, docs, tests, config, release, audit, workflow.
    """
    return ledger_api.record_change(_project_root(), event, sync=True)


@mcp.tool()
@log_tool_call
def get_current_summary() -> str:
    """Return the current release summary markdown."""
    return ledger_api.get_current_summary(_project_root())


@mcp.tool()
@log_tool_call
def sync_ledger() -> dict:
    """Merge all pending fragments into the current release ledger."""
    return ledger_api.sync(_project_root())


@mcp.tool()
@log_tool_call
def get_audit_report() -> dict:
    """Regenerate and return paths to the audit summary and check-in docs."""
    return ledger_api.generate_audit(_project_root())


def main() -> None:
    from audiagentic.foundation.logging import bootstrap
    bootstrap("ledger")
    mcp.run()


if __name__ == "__main__":
    main()
