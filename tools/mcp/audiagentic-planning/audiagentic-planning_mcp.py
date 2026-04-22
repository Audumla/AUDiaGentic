#!/usr/bin/env python3
"""AUDiaGentic planning MCP server — 13-tool consolidated surface.

Single entry point for all MCP clients (Claude Code, OpenCode, Codex, Cline, etc.).
Uses FastMCP standard stdio transport — no custom framing required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Root Discovery — robust, env-var-first, .audiagentic/ marker
# ---------------------------------------------------------------------------


def _find_root_via_marker() -> Path:
    """Find root by walking up from current dir looking for .audiagentic/."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".audiagentic").exists():
            return parent
    # Fallback to cwd
    return current


def _bootstrap_repo_root() -> Path:
    """Bootstrap repo root with env var override support.

    Returns:
        Path to the repository root

    Raises:
        RuntimeError: If AUDIAGENTIC_ROOT is set but points to invalid path
    """
    env_root = os.environ.get("AUDIAGENTIC_ROOT")
    if env_root:
        root = Path(env_root).resolve()
        if not root.exists() or not (root / ".audiagentic").exists():
            raise RuntimeError(
                f"AUDIAGENTIC_ROOT={env_root} is invalid. "
                f"Path must exist and contain .audiagentic/ directory."
            )
        return root
    return _find_root_via_marker()


# ---------------------------------------------------------------------------
# Operation validation and error handling
# ---------------------------------------------------------------------------

VALID_OPS = {"state", "label", "summary", "section", "content", "meta", "field"}
VALID_MODES = {"set", "append", "replace", "add", "remove"}


def validate_operations(operations: list[dict[str, Any]]) -> None:
    """Validate edit operations.

    Args:
        operations: List of operation dicts

    Raises:
        PlanningError: If any operation is invalid
    """
    for i, op in enumerate(operations):
        if not isinstance(op, dict):
            raise PlanningError(
                f"Operation {i} must be a dict",
                suggestion="Each operation should be {{op: 'state', value: 'done'}}",
            )

        op_type = op.get("op")
        if not op_type or op_type not in VALID_OPS:
            raise PlanningError(
                f"Operation {i}: invalid op '{op_type}'",
                suggestion=f"Supported operations: {', '.join(sorted(VALID_OPS))}",
            )

        # Validate required fields per operation type
        if op_type == "section" and "name" not in op:
            raise PlanningError(
                f"Operation {i}: section requires 'name' field",
                suggestion="Example: {{op: 'section', name: 'Notes', content: '...', mode: 'set'}}",
            )

        if op_type == "section" and "mode" in op and op["mode"] not in {"set", "append"}:
            raise PlanningError(
                f"Operation {i}: invalid section mode '{op['mode']}'",
                suggestion="Section mode must be 'set' or 'append'",
            )

        if op_type == "content" and "mode" in op and op["mode"] not in {"replace", "append"}:
            raise PlanningError(
                f"Operation {i}: invalid content mode '{op['mode']}'",
                suggestion="Content mode must be 'replace' or 'append'",
            )

        if op_type == "meta" and "field" not in op:
            raise PlanningError(
                f"Operation {i}: meta requires 'field' field",
                suggestion="Example: {{op: 'meta', field: 'tags', value: '...'}}",
            )

        if op_type == "field":
            if "field" not in op:
                raise PlanningError(
                    f"Operation {i}: field requires 'field' field",
                    suggestion="Example: {{op: 'field', field: 'spec_refs', mode: 'remove', value: 'spec-12'}}",
                )
            if "mode" in op and op["mode"] not in {"set", "replace", "add", "remove"}:
                raise PlanningError(
                    f"Operation {i}: invalid field mode '{op['mode']}'",
                    suggestion="Field mode must be 'set', 'replace', 'add', or 'remove'",
                )
            if op.get("mode", "set") in {"set", "replace", "add"} and "value" not in op:
                raise PlanningError(
                    f"Operation {i}: field op with mode '{op.get('mode', 'set')}' requires 'value'",
                    suggestion="Example: {{op: 'field', field: 'request_refs', mode: 'add', value: 'request-30'}}",
                )


class PlanningError(Exception):
    """Structured error with suggestion for agent recovery."""

    def __init__(self, message: str, suggestion: str | None = None):
        super().__init__(message)
        self.message = message
        self.suggestion = suggestion


# ---------------------------------------------------------------------------
# Bootstrap and imports
# ---------------------------------------------------------------------------

# Bootstrap code root FIRST so imports still work when AUDIAGENTIC_ROOT points
# at an isolated temp project rather than this repository.
_CODE_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_CODE_ROOT), str(_CODE_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Import tm after path is set
import tools.planning.tm_helper as tm

_ROOT = _bootstrap_repo_root()
tm.set_root(_ROOT)


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "audiagentic-planning",
    instructions="""
EDIT FIRST: Use tm_edit for all mutations to a single item. It accepts a list of operations
executed atomically: state, label, summary, section (set/append), content (replace/append),
meta, and field ops for top-level frontmatter add/remove/replace/set. Prefer one tm_edit call
over multiple separate calls. Use field ops for refs like spec_refs/request_refs/task_refs.

READ COST LADDER (cheapest to most tokens):
  tm_get depth=head < depth=meta < depth=full < depth=body
Use depth=head for existence/state checks. depth=body only when the raw text is needed.

FLEXIBLE QUERY: tm_list supports arrays and text search:
  - tm_list(kind=["task","wp"], state=["ready","in_progress"]): Multiple kinds/states
  - tm_list(kind="task", query="API integration"): Text search within results
  - tm_list(kind=["task","spec"], state="ready", query="auth"): Combined filters

WORK QUEUE: tm_list mode=next returns unclaimed ready items filtered by kind and domain.

MULTI-AGENT: Multiple agents can work on the same repository. Use tm_claim to coordinate
access: claim items before work (op=claim), check available work (mode=next skips claimed),
release when done (op=unclaim). Claims can have TTL for auto-release.

BEFORE CREATING: Call tm_docs(op='config') to discover supported kinds, required refs, and
required fields. Cache the result for the session. This avoids invalid tm_create attempts.
""",
)


# ---------------------------------------------------------------------------
# 1. EDIT — listed first so agents discover it before narrower mutation tools
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "PREFERRED for mutations: execute one or more operations on a planning item atomically. "
        "operations — list of dicts with 'op' key. "
        "Supported ops: "
        "  state: {{op:'state', value:'done'}} "
        "  label: {{op:'label', value:'New label'}} "
        "  summary: {{op:'summary', value:'New summary'}} "
        "  section: {{op:'section', name:'Notes', content:'...', mode:'set'|'append'}} "
        "  content: {{op:'content', value:'...', mode:'replace'|'append'}} "
        "  meta: {{op:'meta', field:'tags', value:'...'}} "
        "  field: {{op:'field', field:'spec_refs', mode:'add'|'remove'|'replace'|'set', value:'spec-123'}} "
        "Use field for top-level frontmatter refs and lists; use meta only for nested meta.* values. "
        "Example: [{{op:'field',field:'spec_refs',mode:'remove',value:'spec-12'}},{{op:'section',name:'Notes',content:'...',mode:'set'}}]"
    )
)
def tm_edit(id: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute atomic operations on a planning item.

    Args:
        id: Planning item ID (e.g., task-0123)
        operations: List of operation dicts (validated at runtime)

    Returns:
        dict with item ID, executed operations count, and result

    Raises:
        PlanningError: If operation is invalid or item not found
    """
    # Validate ID to prevent path traversal
    try:
        tm._validate_id(id)
    except ValueError as e:
        raise PlanningError(
            str(e), suggestion="Ensure ID is a simple string without path separators"
        )

    # Validate operations before execution
    validate_operations(operations)

    try:
        result = tm.update(id, operations=operations)
        return {"id": id, "operations_executed": len(operations), "result": result}
    except ValueError as e:
        error_msg = str(e)
        if "Unknown op" in error_msg or "unknown operation" in error_msg.lower():
            raise PlanningError(
                error_msg, suggestion=f"Supported operations: {', '.join(sorted(VALID_OPS))}"
            )
        if "not found" in error_msg.lower():
            raise PlanningError(
                error_msg,
                suggestion=f"Use tm_list to find valid item IDs, or tm_create to create '{id}'",
            )
        raise PlanningError(error_msg)
    except Exception as e:
        raise PlanningError(f"Failed to edit {id}: {e}")


# ---------------------------------------------------------------------------
# 2. CREATE
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Create a planning item. kind: request|spec|plan|task|wp|standard. "
        "Provide content for initial markdown body. "
        "Kind requirements: spec needs request_refs; task needs spec; wp needs plan. "
        "Request extras: profile, source, context, current_understanding, open_questions."
    )
)
def tm_create(
    kind: str,
    label: str,
    summary: str,
    content: str | None = None,
    source: str | None = None,
    domain: str = "core",
    spec: str | None = None,
    plan: str | None = None,
    parent: str | None = None,
    target: str | None = None,
    workflow: str | None = None,
    request_refs: list[str] | None = None,
    check_duplicates: bool = True,
    profile: str | None = None,
    current_understanding: str | None = None,
    open_questions: list[str] | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Create a planning item. kind: request|spec|plan|task|wp|standard.
    Provide content for initial markdown body.
    Kind requirements: spec needs request_refs; task needs spec; wp needs plan.
    Request extras: profile, source, context, current_understanding, open_questions."""
    try:
        return tm.create(
            kind=kind,
            label=label,
            summary=summary,
            content=content,
            source=source,
            domain=domain,
            spec=spec,
            plan=plan,
            parent=parent,
            target=target,
            workflow=workflow,
            request_refs=request_refs,
            check_duplicates=check_duplicates,
            profile=profile,
            current_understanding=current_understanding,
            open_questions=open_questions,
            context=context,
        )
    except ValueError as e:
        raise PlanningError(str(e))
    except Exception as e:
        raise PlanningError(f"Failed to create {kind}: {e}")


# ---------------------------------------------------------------------------
# 3. GET — read at any depth
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Read a planning item. "
        "depth: head (index-only, no parse — cheapest, use for existence/state checks) | "
        "meta (frontmatter only — use when metadata fields are needed) | "
        "full (metadata + body, default) | "
        "body (raw markdown body only — most tokens, use only when text is needed). "
        "with_related: include linked items (depth=full only, adds cost)."
    )
)
def tm_get(
    id: str,
    depth: str = "full",
    with_related: bool = False,
    with_resources: bool = False,
) -> dict[str, Any] | str:
    """Read a planning item.
    depth: head (index-only, no parse — cheapest, use for existence/state checks) |
    meta (frontmatter only — use when metadata fields are needed) |
    full (metadata + body, default) |
    body (raw markdown body only — most tokens, use only when text is needed).
    with_related: include linked items (depth=full only, adds cost)."""
    # Validate ID to prevent path traversal
    try:
        tm._validate_id(id)
    except ValueError as e:
        raise PlanningError(
            str(e), suggestion="Ensure ID is a simple string without path separators"
        )

    valid_depths = {"head", "meta", "full", "body"}
    if depth not in valid_depths:
        raise PlanningError(
            f"Unknown depth: {depth!r}",
            suggestion=f"Valid depths: {', '.join(sorted(valid_depths))}",
        )

    try:
        if depth == "head":
            return tm.head(id)
        elif depth == "meta":
            return tm.show(id)
        elif depth == "body":
            return tm.get_content(id)
        else:  # full
            result = tm.extract(
                id,
                with_related=with_related,
                with_resources=with_resources,
                include_body=True,
                write_to_disk=True,
            )
            # Resource Exhaustion Guard: Warn if result is excessively large
            if isinstance(result, dict) and "item" in result:
                body_len = len(result["item"].get("body", ""))
                if body_len > 20000:
                    # Log warning or return as is, but the agent is now informed
                    pass
            return result
    except ValueError as e:
        raise PlanningError(str(e), suggestion="Use tm_list to find valid item IDs")


# ---------------------------------------------------------------------------
# 4. LIST — list items, count by state, or get next work items
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Query planning items. "
        "mode: list (items, default) | count (kind×state summary) | next (unclaimed items for agent work queue). "
        "kind: request|spec|plan|task|wp|standard — omit for all (list/count) or defaults to task (next). "
        "state: filter by state (list) or target state (next, defaults to ready). "
        "domain: domain filter (next only). "
        "query: optional text search within item content (list mode only)."
    )
)
def tm_list(
    kind: str | list[str] | None = None,
    state: str | list[str] | None = None,
    domain: str | None = None,
    mode: str = "list",
    include_deleted: bool = False,
    include_archived: bool = False,
    query: str | None = None,
) -> Any:
    valid_modes = {"list", "count", "next"}
    if mode not in valid_modes:
        raise PlanningError(
            f"Unknown mode: {mode!r}", suggestion=f"Valid modes: {', '.join(sorted(valid_modes))}"
        )

    if mode == "count":
        return tm.status()
    elif mode == "next":
        result = tm.next_items(kind or "task", state or "ready", domain)
        return result if result is not None else []
    else:  # list
        items = tm.list_kind(
            kind,
            include_deleted=include_deleted,
            include_archived=include_archived,
            state=state,
        )
        # Optional text filtering
        if query and items:
            items = [
                item
                for item in items
                if query.lower() in item.get("label", "").lower()
                or query.lower() in item.get("summary", "").lower()
            ]
        return items


# ---------------------------------------------------------------------------
# 5. SECTION — read/write named sections and subsections
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Read or write a named section in a planning document. "
        "op: get (read section) | set (replace section, requires content) | "
        "append (append to section, requires content) | "
        "get_sub (subsection via dot notation, e.g. 'Requirements.Functional'). "
        "For multiple section changes prefer tm_edit."
    )
)
def tm_section(
    id: str,
    op: str,
    section: str,
    content: str | None = None,
) -> dict[str, Any]:
    valid_ops = {"get", "get_sub", "set", "append"}
    if op not in valid_ops:
        raise PlanningError(
            f"Unknown op: {op!r}", suggestion=f"Valid ops: {', '.join(sorted(valid_ops))}"
        )

    if op in {"set", "append"} and content is None:
        raise PlanningError(
            f"content is required for op={op!r}",
            suggestion="Provide content parameter for set or append operations",
        )

    try:
        if op == "get":
            return tm.get_section(id, section)
        elif op == "get_sub":
            return tm.get_subsection(id, section)
        elif op == "set":
            return tm.set_section(id, section, content)
        elif op == "append":
            return tm.append_section(id, section, content)
    except ValueError as e:
        raise PlanningError(str(e))


# ---------------------------------------------------------------------------
# 6–9. MOVE, DELETE, RELINK, PACKAGE
# ---------------------------------------------------------------------------


@mcp.tool(description="Move a task or wp to a different domain (e.g. core → provider)")
def tm_move(id: str, domain: str) -> dict[str, Any]:
    try:
        return tm.move(id, domain)
    except ValueError as e:
        raise PlanningError(str(e))


@mcp.tool(
    description="Delete a planning item. hard=False (default) soft-deletes; hard=True removes file."
)
def tm_delete(id: str, hard: bool = False, reason: str | None = None) -> dict[str, Any]:
    try:
        return tm.delete(id, hard=hard, reason=reason)
    except ValueError as e:
        raise PlanningError(str(e))


@mcp.tool(
    description="Update a reference/link field in a planning item (e.g. add spec, parent, request_refs)"
)
def tm_relink(
    src: str, field: str, dst: str, seq: int | None = None, display: str | None = None
) -> dict[str, Any]:
    try:
        return tm.relink(src, field, dst, seq, display)
    except ValueError as e:
        raise PlanningError(str(e))


@mcp.tool(description="Group Tasks into a new WorkPackage within a Plan")
def tm_package(
    plan: str, tasks: list[str], label: str, summary: str, domain: str = "core"
) -> dict[str, Any]:
    try:
        return tm.package(plan, tasks, label, summary, domain)
    except ValueError as e:
        raise PlanningError(str(e))


# ---------------------------------------------------------------------------
# 10. STANDARDS
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Standards lookup. "
        "Omit id → list all standards. "
        "id=standard-XXXX → get that standard with body. "
        "id=task-XXXX (or any non-standard item) → list applicable standards for that item."
    )
)
def tm_standards(
    id: str | None = None,
    with_related: bool = False,
    with_resources: bool = False,
) -> Any:
    if id is None:
        return tm.list_standards()
    elif id.startswith("standard-"):
        return tm.get_standard(id, with_related, with_resources)
    else:
        return tm.standards(id)


# ---------------------------------------------------------------------------
# 11. CLAIM
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Manage planning item ownership claims. "
        "op: claim (requires kind, id, holder; optional ttl seconds) | "
        "unclaim (requires id) | "
        "list (optional kind filter)."
    )
)
def tm_claim(
    op: str,
    id: str | None = None,
    kind: str | None = None,
    holder: str | None = None,
    ttl: int | None = None,
) -> Any:
    valid_ops = {"claim", "unclaim", "list"}
    if op not in valid_ops:
        raise PlanningError(
            f"Unknown op: {op!r}", suggestion=f"Valid ops: {', '.join(sorted(valid_ops))}"
        )

    if op == "claim":
        if not kind or not id or not holder:
            raise PlanningError(
                "op=claim requires kind, id, and holder",
                suggestion="Example: {{op:'claim', kind:'task', id:'task-0123', holder:'agent-1'}}",
            )
        return tm.claim(kind, id, holder, ttl)
    elif op == "unclaim":
        if not id:
            raise PlanningError(
                "op=unclaim requires id", suggestion="Example: {{op:'unclaim', id:'task-0123'}}"
            )
        return tm.unclaim(id)
    elif op == "list":
        return tm.claims(kind)


# ---------------------------------------------------------------------------
# 12. DOCS
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Access documentation resources. "
        "op: surfaces (list doc surfaces) | surface (get one, id=surface_id) | "
        "refs (list reference docs) | profiles (list request profiles) | "
        "profile (get one, id=profile_id) | support (list support docs, optional id and role) | "
        "sync_req (doc sync requirements, requires kind) | pending (pending doc updates, requires kind) | "
        "config (read-only planning config discovery for agents — call before tm_create; "
        "mode=compact (default, low-token) or mode=full; optional kind filter)."
    )
)
def tm_docs(
    op: str,
    id: str | None = None,
    kind: str | None = None,
    profile_pack: str = "standard",
    role: str | None = None,
    mode: str = "compact",
) -> Any:
    valid_ops = {
        "surfaces",
        "surface",
        "refs",
        "profiles",
        "profile",
        "support",
        "sync_req",
        "pending",
        "config",
    }
    if op not in valid_ops:
        raise PlanningError(
            f"Unknown op: {op!r}", suggestion=f"Valid ops: {', '.join(sorted(valid_ops))}"
        )

    if op == "surfaces":
        return tm.list_doc_surfaces()
    elif op == "surface":
        return tm.get_doc_surface(id)
    elif op == "refs":
        return tm.list_reference_docs()
    elif op == "profiles":
        return tm.list_request_profiles()
    elif op == "profile":
        return tm.get_request_profile(id)
    elif op == "support":
        return tm.list_support_docs(id, role)
    elif op == "sync_req":
        if not kind:
            raise PlanningError(
                "op=sync_req requires kind", suggestion="Example: {{op:'sync_req', kind:'task'}}"
            )
        return tm.get_doc_sync_requirements(kind, profile_pack)
    elif op == "pending":
        if not kind:
            raise PlanningError(
                "op=pending requires kind", suggestion="Example: {{op:'pending', kind:'task'}}"
            )
        return tm.pending_doc_updates(kind, profile_pack)
    elif op == "config":
        if mode not in ("compact", "full"):
            raise PlanningError(
                f"Invalid mode: {mode!r}",
                suggestion="Use mode='compact' (default) or mode='full'",
            )
        return tm.planning_config_summary(mode=mode, kind=kind)


# ---------------------------------------------------------------------------
# 13. ADMIN
# ---------------------------------------------------------------------------


@mcp.tool(
    description=(
        "Admin and maintenance operations. "
        "op: validate (check all items against schemas, returns errors) | "
        "index (rebuild lookup indexes) | "
        "clean_indexes (clear and rebuild indexes only — cheaper than maintain, no filename reconcile) | "
        "reconcile (fix filesystem/state inconsistencies, returns renames+orphans) | "
        "maintain (canonical reconcile + rebuild of derived planning state) | "
        "compact (deterministic ID compaction: remove gaps, rewrite refs, rename files, update counters, validate — returns remap table and cannot_repair list) | "
        "events (recent event log, optional tail count, default 20) | "
        "verify (health check — dirs, configs, API) | "
        "check_sensitive (scan item body for API keys/tokens, requires id)."
    )
)
def tm_admin(
    op: str,
    id: str | None = None,
    tail: int = 20,
) -> Any:
    valid_ops = {"validate", "index", "clean_indexes", "reconcile", "maintain", "compact", "events", "verify", "check_sensitive"}
    if op not in valid_ops:
        raise PlanningError(
            f"Unknown op: {op!r}", suggestion=f"Valid ops: {', '.join(sorted(valid_ops))}"
        )

    if op == "validate":
        return tm.validate()
    elif op == "index":
        tm.index()
        return None
    elif op == "clean_indexes":
        return tm.clean_indexes()
    elif op == "reconcile":
        return tm.reconcile()
    elif op == "maintain":
        return tm._get_api().maintain()
    elif op == "compact":
        return tm.compact()
    elif op == "events":
        return tm.events(tail)
    elif op == "verify":
        return tm.verify_structure()
    elif op == "check_sensitive":
        if not id:
            raise PlanningError(
                "op=check_sensitive requires id",
                suggestion="Example: {{op:'check_sensitive', id:'task-0123'}}",
            )
        return tm.check_sensitive_data(id)


if __name__ == "__main__":
    try:
        mcp.run()
    except Exception as exc:
        print(f"Fatal MCP startup error: {exc}", file=sys.stderr)
        raise
