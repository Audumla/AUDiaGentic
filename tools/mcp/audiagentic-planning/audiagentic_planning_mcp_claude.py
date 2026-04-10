#!/usr/bin/env python3
"""AUDiaGentic planning MCP server - Claude stdio launcher.

This version is intentionally simple for Claude/VS Code:
- uses FastMCP's standard stdio transport
- avoids custom framing logic
- keeps stdout clean for MCP JSON-RPC traffic
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def _bootstrap_repo_root() -> Path:
    markers = (("tools", "planning", "tm_helper.py"),)
    search_roots = [
        Path.cwd(),
        *Path.cwd().parents,
        Path(__file__).resolve().parent,
        *Path(__file__).resolve().parent.parents,
    ]
    for candidate in search_roots:
        if any((candidate / Path(*marker)).exists() for marker in markers):
            return candidate
    raise RuntimeError(
        f"Could not locate repository root for planning MCP import. "
        f"Searched from cwd={Path.cwd()} and module={Path(__file__).resolve()}"
    )


_BOOTSTRAP_ROOT = _bootstrap_repo_root()
for _p in (str(_BOOTSTRAP_ROOT), str(_BOOTSTRAP_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

import tools.planning.tm_helper as tm


_ROOT = tm._find_project_root()
if os.environ.get("AUDIAGENTIC_ROOT"):
    tm.set_root(Path(os.environ["AUDIAGENTIC_ROOT"]).resolve())
    _ROOT = tm._get_root()

for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

mcp = FastMCP("audiagentic-planning")


def _wrap_tool_result(func):
    """Wrap list/None results so FastMCP emits a single content block."""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if isinstance(result, list) or result is None:
            return {"_result": result}
        return result

    return wrapper


def tool_with_empty_list_fix(description=None):
    def decorator(func):
        wrapped = _wrap_tool_result(func)
        return mcp.tool(description=description)(wrapped)
    return decorator


@mcp.tool(description="Create a new Request planning document with duplicate detection")
def tm_new_request(
    label: str,
    summary: str,
    profile: str | None = None,
    current_understanding: str | None = None,
    open_questions: list[str] | None = None,
    source: str | None = None,
    context: str | None = None,
    check_duplicates: bool = True,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "profile": profile,
        "current_understanding": current_understanding,
        "open_questions": open_questions,
        "context": context,
        "check_duplicates": check_duplicates,
    }
    if source is not None:
        kwargs["source"] = source
    return tm.new_request(label, summary, **kwargs)


@mcp.tool(description="Create a new Specification planning document with duplicate detection")
def tm_new_spec(
    label: str,
    summary: str,
    request_refs: list[str] | None = None,
    check_duplicates: bool = True,
) -> dict[str, Any]:
    return tm.new_spec(label, summary, request_refs, check_duplicates=check_duplicates)


@mcp.tool(description="Create a new Plan planning document, optionally linked to a Specification")
def tm_new_plan(
    label: str,
    summary: str,
    spec: str | None = None,
    request_refs: list[str] | None = None,
) -> dict[str, Any]:
    return tm.new_plan(label, summary, spec, request_refs)


@mcp.tool(description="Create a new Task planning document with spec, optional target packet, parent, and workflow")
def tm_new_task(
    label: str,
    summary: str,
    spec: str,
    domain: str = "core",
    target: str | None = None,
    parent: str | None = None,
    workflow: str | None = None,
    request_refs: list[str] | None = None,
) -> dict[str, Any]:
    return tm.new_task(label, summary, spec, domain, target, parent, workflow, request_refs)


@mcp.tool(description="Soft delete a planning item by default, or hard delete it and sync counters")
def tm_delete(
    id: str,
    hard: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    return tm.delete(id, hard=hard, reason=reason)


@mcp.tool(description="Create a new WorkPackage planning document linked to a Plan")
def tm_new_wp(
    label: str,
    summary: str,
    plan: str,
    domain: str = "core",
    workflow: str | None = None,
) -> dict[str, Any]:
    return tm.new_wp(label, summary, plan, domain, workflow)


@mcp.tool(description="Create a new Standard planning document")
def tm_new_standard(label: str, summary: str) -> dict[str, Any]:
    return tm.new_standard(label, summary)


@mcp.tool(description="Change the state of a planning item (e.g., ready → in_progress → done)")
def tm_state(id: str, new_state: str) -> dict[str, Any]:
    return tm.state(id, new_state)


@mcp.tool(description="Move a planning item to a different domain (e.g., core → contrib)")
def tm_move(id: str, domain: str) -> dict[str, Any]:
    return tm.move(id, domain)


@mcp.tool(description="Update label, summary, or body text of a planning item")
def tm_update(
    id: str,
    label: str | None = None,
    summary: str | None = None,
    append: str | None = None,
    operations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return tm.update(id, label, summary, append, operations=operations)


@mcp.tool(description="Execute multiple operations on a planning item atomically (state changes, section updates, etc.)")
def tm_batch_update(
    id: str,
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    return tm.update(id, operations=operations)


@mcp.tool(description="Get the full markdown content of a planning document")
def tm_get_content(id: str) -> str:
    return tm.get_content(id)


@mcp.tool(description="Update content of a planning document (replace, append, or insert at position)")
def tm_update_content(
    id: str,
    content: str,
    mode: str = "replace",
    section: str | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    return tm.update_content(id, content, mode, section, position)


@mcp.tool(description="Create a new planning document of any kind with initial content in one operation")
def tm_create_with_content(
    kind: str,
    label: str,
    summary: str,
    content: str,
    source: str | None = None,
    domain: str = "core",
    spec: str | None = None,
    plan: str | None = None,
    parent: str | None = None,
    target: str | None = None,
    workflow: str | None = None,
    request_refs: list[str] | None = None,
) -> dict[str, Any]:
    return tm.create_with_content(
        kind, label, summary, content, source, domain, spec, plan, parent, target, workflow, request_refs
    )


@mcp.tool(description="Update a link field in a planning item (e.g., add/change spec, parent, or related items)")
def tm_relink(
    src: str, field: str, dst: str, seq: int | None = None, display: str | None = None
) -> dict[str, Any]:
    return tm.relink(src, field, dst, seq, display)


@mcp.tool(description="Group multiple Tasks into a new WorkPackage within a Plan")
def tm_package(
    plan: str, tasks: list[str], label: str, summary: str, domain: str = "core"
) -> dict[str, Any]:
    return tm.package(plan, tasks, label, summary, domain)


@tool_with_empty_list_fix(description="List planning items, optionally filtered by kind")
def tm_list(
    kind: str | None = None,
    include_deleted: bool = False,
) -> Any:
    return tm.list_kind(kind, include_deleted=include_deleted)


@mcp.tool(description="Get frontmatter metadata for a single planning item via one file parse. No body content.")
def tm_show(id: str) -> dict[str, Any]:
    return tm.show(id)


@mcp.tool(description="Return a planning extract. Can include related refs, resources, and optionally body content.")
def tm_extract(
    id: str,
    with_related: bool = False,
    with_resources: bool = False,
    include_body: bool = True,
    write_to_disk: bool = True,
) -> dict[str, Any]:
    return tm.extract(id, with_related, with_resources, include_body, write_to_disk)


@mcp.tool(description="Return lean index-only metadata for a planning item. No markdown parse. Lowest token cost.")
def tm_head(id: str) -> dict[str, Any]:
    return tm.head(id)


@tool_with_empty_list_fix(description="List Tasks in a given state")
def tm_next_tasks(state: str = "ready", domain: str | None = None) -> Any:
    return tm.next_tasks(state, domain)


@tool_with_empty_list_fix(description="List items of a given kind in a given state")
def tm_next_items(kind: str = "task", state: str = "ready", domain: str | None = None) -> Any:
    return tm.next_items(kind, state, domain)


@mcp.tool(description="Get summary counts of all planning items grouped by kind and state")
def tm_status() -> dict[str, Any]:
    return tm.status()


@tool_with_empty_list_fix(description="List applicable standards for a planning item")
def tm_standards(id: str) -> Any:
    return tm.standards(id)


@tool_with_empty_list_fix(description="List all standard planning documents")
def tm_list_standards() -> Any:
    return tm.list_standards()


@mcp.tool(description="Get a standard planning document with metadata and body")
def tm_get_standard(
    standard_id: str, with_related: bool = False, with_resources: bool = False
) -> dict[str, Any]:
    return tm.get_standard(standard_id, with_related, with_resources)


@tool_with_empty_list_fix(description="List all documentation surfaces")
def tm_list_doc_surfaces() -> Any:
    return tm.list_doc_surfaces()


@tool_with_empty_list_fix(description="Get a specific documentation surface by ID")
def tm_get_doc_surface(surface_id: str) -> Any:
    return tm.get_doc_surface(surface_id)


@tool_with_empty_list_fix(description="List reference documentation that applies to planning items")
def tm_list_reference_docs() -> Any:
    return tm.list_reference_docs()


@tool_with_empty_list_fix(description="List available request profiles")
def tm_list_request_profiles() -> Any:
    return tm.list_request_profiles()


@tool_with_empty_list_fix(description="Get a specific request profile by ID")
def tm_get_request_profile(profile_id: str) -> Any:
    return tm.get_request_profile(profile_id)


@tool_with_empty_list_fix(description="List supporting documentation (sidecars) for a planning item or by role")
def tm_list_support_docs(
    supports_id: str | None = None, role: str | None = None
) -> Any:
    return tm.list_support_docs(supports_id, role)


@mcp.tool(description="Get a named section from a planning document")
def tm_get_section(id: str, section: str) -> dict[str, Any]:
    return tm.get_section(id, section)


@mcp.tool(description="Replace the content of a named section in a planning document")
def tm_set_section(id: str, section: str, content: str) -> dict[str, Any]:
    return tm.set_section(id, section, content)


@mcp.tool(description="Append content to a named section in a planning document")
def tm_append_section(id: str, section: str, content: str) -> dict[str, Any]:
    return tm.append_section(id, section, content)


@mcp.tool(description="Get nested subsection content using dot notation")
def tm_get_subsection(id: str, section_path: str) -> dict[str, Any]:
    return tm.get_subsection(id, section_path)


@mcp.tool(description="Get documentation sync requirements for a planning item kind and profile pack")
def tm_doc_sync_requirements(kind: str, profile_pack: str = "standard") -> dict[str, Any]:
    return tm.get_doc_sync_requirements(kind, profile_pack)


@tool_with_empty_list_fix(description="List pending documentation updates needed for a planning item kind")
def tm_pending_doc_updates(kind: str, profile_pack: str = "standard") -> Any:
    return tm.pending_doc_updates(kind, profile_pack)


@mcp.tool(description="Claim ownership of a planning item with optional TTL")
def tm_claim(kind: str, id: str, holder: str, ttl: int | None = None) -> dict[str, Any]:
    return tm.claim(kind, id, holder, ttl)


@tool_with_empty_list_fix(description="Release ownership of a planning item")
def tm_unclaim(id: str) -> Any:
    return tm.unclaim(id)


@tool_with_empty_list_fix(description="List active claims on planning items")
def tm_claims(kind: str | None = None) -> Any:
    return tm.claims(kind)


@tool_with_empty_list_fix(description="Validate all planning documents against schemas and rules")
def tm_validate() -> Any:
    return tm.validate()


@tool_with_empty_list_fix(description="Re-index all planning documents")
def tm_index() -> Any:
    tm.index()


@tool_with_empty_list_fix(description="Reconcile planning state with filesystem")
def tm_reconcile() -> Any:
    return tm.reconcile()


@tool_with_empty_list_fix(description="Get recent planning events from the event log")
def tm_events(tail: int = 20) -> Any:
    return tm.events(tail)


@mcp.tool(description="Verify planning module structure is healthy")
def tm_verify_structure() -> dict[str, Any]:
    return tm.verify_structure()

if __name__ == "__main__":
    try:
        mcp.run()
    except Exception as exc:
        print(f"Fatal MCP startup error: {exc}", file=sys.stderr)
        raise

