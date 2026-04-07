#!/usr/bin/env python3
"""AUDiaGentic planning MCP server - exposes planning tools to AI agents."""

from __future__ import annotations
import sys
from pathlib import Path
from typing import Any

# Auto-detect project root
_ROOT = None
for p in [Path.cwd(), *Path.cwd().parents]:
    if (p / ".audiagentic" / "planning").exists():
        _ROOT = p
        break
if _ROOT is None:
    _ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)
import tools.planning.tm_helper as tm

mcp = FastMCP("audiagentic-planning")


# CREATE OBJECTS
@mcp.tool()
def tm_new_request(label: str, summary: str) -> dict[str, Any]:
    """Create a request (raw requirement capture)."""
    return tm.new_request(label, summary)


@mcp.tool()
def tm_new_spec(
    label: str, summary: str, request_refs: list[str] | None = None
) -> dict[str, Any]:
    """Create a specification (detailed technical spec)."""
    return tm.new_spec(label, summary, request_refs)


@mcp.tool()
def tm_new_plan(label: str, summary: str, spec: str | None = None) -> dict[str, Any]:
    """Create a plan (delivery plan)."""
    return tm.new_plan(label, summary, spec)


@mcp.tool()
def tm_new_task(
    label: str,
    summary: str,
    spec: str,
    domain: str = "core",
    target: str | None = None,
    parent: str | None = None,
    workflow: str | None = None,
) -> dict[str, Any]:
    """Create a task (individual work item)."""
    return tm.new_task(label, summary, spec, domain, target, parent)


@mcp.tool()
def tm_new_wp(
    label: str,
    summary: str,
    plan: str,
    domain: str = "core",
    workflow: str | None = None,
) -> dict[str, Any]:
    """Create a work package (grouped tasks)."""
    return tm.new_wp(label, summary, plan, domain)


@mcp.tool()
def tm_new_standard(label: str, summary: str) -> dict[str, Any]:
    """Create a standard (reusable template)."""
    return tm.new_standard(label, summary)


# LIFECYCLE
@mcp.tool()
def tm_state(id: str, new_state: str) -> dict[str, Any]:
    """Change object state (validates transitions)."""
    return tm.state(id, new_state)


@mcp.tool()
def tm_move(id: str, domain: str) -> dict[str, Any]:
    """Move task or work package to domain."""
    return tm.move(id, domain)


@mcp.tool()
def tm_update(
    id: str,
    label: str | None = None,
    summary: str | None = None,
    append: str | None = None,
) -> dict[str, Any]:
    """Update an object."""
    return tm.update(id, label, summary, append)


# CONTENT MANAGEMENT
@mcp.tool()
def tm_get_content(id: str) -> str:
    """Get markdown content without YAML frontmatter."""
    return tm.get_content(id)


@mcp.tool()
def tm_update_content(
    id: str,
    content: str,
    mode: str = "replace",
    section: str | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    """Update file content with various modes.

    Args:
        id: Object ID to update
        content: Markdown content to write
        mode: 'replace', 'append', 'insert', or 'section'
        section: Section header to update (for mode='section')
        position: Line position to insert (for mode='insert')
    """
    return tm.update_content(id, content, mode, section, position)


@mcp.tool()
def tm_create_with_content(
    kind: str,
    label: str,
    summary: str,
    content: str,
    domain: str = "core",
    spec: str | None = None,
    plan: str | None = None,
    parent: str | None = None,
    target: str | None = None,
    workflow: str | None = None,
    request_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Create planning object with full content.

    Args:
        kind: Object type (plan/request/spec/task/wp/standard)
        label: Object label
        summary: Object summary
        content: Full markdown content (without YAML frontmatter)
        domain: Domain for task/wp
        spec: Spec reference for plan/task
        plan: Plan reference for wp
        parent: Parent task reference
        target: Target reference
        workflow: Workflow name
        request_refs: Request references for spec
    """
    return tm.create_with_content(
        kind,
        label,
        summary,
        content,
        domain,
        spec,
        plan,
        parent,
        target,
        workflow,
        request_refs,
    )


# RELATIONSHIPS
@mcp.tool()
def tm_relink(
    src: str,
    field: str,
    dst: str,
    seq: int | None = None,
    display: str | None = None,
) -> dict[str, Any]:
    """Create a relationship between objects."""
    return tm.relink(src, field, dst, seq, display)


@mcp.tool()
def tm_package(
    plan: str,
    tasks: list[str],
    label: str,
    summary: str,
    domain: str = "core",
) -> dict[str, Any]:
    """Create a work package from tasks."""
    return tm.package(plan, tasks, label, summary, domain)


# QUERIES
@mcp.tool()
def tm_list(kind: str | None = None) -> list[dict[str, Any]]:
    """List objects, optionally filtered by kind."""
    return tm.list_kind(kind)


@mcp.tool()
def tm_show(id: str) -> dict[str, Any]:
    """Show object details."""
    return tm.show(id)


@mcp.tool()
def tm_extract(
    id: str,
    with_related: bool = False,
    with_resources: bool = False,
) -> dict[str, Any]:
    """Extract object with optional context."""
    return tm.extract(id, with_related, with_resources)


@mcp.tool()
def tm_next_tasks(
    state: str = "ready", domain: str | None = None
) -> list[dict[str, Any]]:
    """Get next available tasks."""
    return tm.next_tasks(state, domain)


@mcp.tool()
def tm_next_items(
    kind: str = "task",
    state: str = "ready",
    domain: str | None = None,
) -> list[dict[str, Any]]:
    """Get next available items."""
    return tm.next_items(kind, state, domain)


@mcp.tool()
def tm_status() -> dict[str, Any]:
    """Get status summary by kind/state."""
    return tm.status()


@mcp.tool()
def tm_standards(id: str) -> list[str]:
    """Get effective standards for object."""
    return tm.standards(id)


# CLAIMS
@mcp.tool()
def tm_claim(kind: str, id: str, holder: str, ttl: int | None = None) -> dict[str, Any]:
    """Claim an object (prevent duplicate work)."""
    return tm.claim(kind, id, holder, ttl)


@mcp.tool()
def tm_unclaim(id: str) -> bool:
    """Release a claim."""
    return tm.unclaim(id)


@mcp.tool()
def tm_claims(kind: str | None = None) -> list[dict[str, Any]]:
    """List claims."""
    return tm.claims(kind)


# MAINTENANCE
@mcp.tool()
def tm_validate() -> list[str]:
    """Validate all planning objects. Returns errors (empty if valid)."""
    return tm.validate()


@mcp.tool()
def tm_index() -> None:
    """Rebuild indexes."""
    tm.index()


@mcp.tool()
def tm_reconcile() -> dict[str, Any]:
    """Reconcile planning objects."""
    return tm.reconcile()


# EVENTS
@mcp.tool()
def tm_events(tail: int = 20) -> list[dict[str, Any]]:
    """Get recent events."""
    return tm.events(tail)


if __name__ == "__main__":
    mcp.run()
