#!/usr/bin/env python3
"""Config-driven MCP planning server — introspects PlanningAPI at startup.

Every tool, operation, state, and parameter is derived from the PlanningAPI.
No kind names, state names, operation types, or modes are hardcoded here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("Error: mcp package not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = Path(__import__("os").environ.get("AUDIAGENTIC_ROOT", ""))
    if env_root and (env_root / ".audiagentic").exists():
        return env_root.resolve()
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / ".audiagentic").exists():
            return p.resolve()
    return Path(__file__).resolve().parents[3]


_CODE_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_CODE_ROOT), str(_CODE_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.api import PlanningAPI

_ROOT = _find_root()
_api = PlanningAPI(_ROOT)
_mcp = FastMCP("audiagentic-planning")


# ---------------------------------------------------------------------------
# Introspection — build tool metadata from API
# ---------------------------------------------------------------------------


def _discover_kinds() -> list[str]:
    return _api.config.all_kinds()


def _discover_states(kind: str, workflow: str | None = None) -> list[str]:
    try:
        return _api.config.workflow_states(kind, workflow)
    except Exception:
        return []


def _discover_initial_states(kind: str, workflow: str | None = None) -> list[str]:
    try:
        wf = _api.config.workflow_for(kind, workflow)
        return wf.get("initial", [])
    except Exception:
        return []


def _discover_active_states(kind: str, workflow: str | None = None) -> list[str]:
    try:
        wf = _api.config.workflow_for(kind, workflow)
        return wf.get("active", [])
    except Exception:
        return []


def _discover_blocked_states(kind: str, workflow: str | None = None) -> list[str]:
    try:
        wf = _api.config.workflow_for(kind, workflow)
        return wf.get("blocked", [])
    except Exception:
        return []


def _discover_complete_states(kind: str, workflow: str | None = None) -> list[str]:
    try:
        wf = _api.config.workflow_for(kind, workflow)
        return wf.get("complete", [])
    except Exception:
        return []


def _discover_terminal_states(kind: str, workflow: str | None = None) -> list[str]:
    try:
        wf = _api.config.workflow_for(kind, workflow)
        return wf.get("terminal", [])
    except Exception:
        return []


def _discover_lifecycle_actions() -> list[str]:
    return list(_api.config.lifecycle_actions().keys())


def _discover_lifecycle_action_transitions(action_name: str) -> dict[str, Any]:
    try:
        action = _api.config.lifecycle_action(action_name)
        return {
            "transition_to": action.get("transition_to", ""),
            "metadata_fields": _api.config.lifecycle_metadata_fields(),
        }
    except Exception:
        return {}


def _discover_reference_fields(kind: str) -> list[str]:
    try:
        return _api.config.reference_fields(kind)
    except Exception:
        return []


def _discover_reference_field_info(field: str) -> dict[str, Any]:
    shape = _api.config.reference_field_shape(field)
    targets = _api.config.reference_field_targets(field)
    return {"shape": shape, "targets": targets}


def _discover_creation_profiles() -> list[str]:
    return list(_api.config.creation_profiles().keys())


def _discover_creation_profile(name: str) -> dict[str, Any]:
    try:
        return _api.config.creation_profile_for(name)
    except Exception:
        return {}


def _discover_default_reference_field() -> str:
    return _api.config.default_reference_field()


def _discover_kind_config(kind: str) -> dict[str, Any]:
    return _api.config.kind_config(kind)


def _discover_all_reference_fields() -> list[str]:
    return _api.config.all_reference_fields()


def _discover_queue_defaults() -> dict[str, str]:
    try:
        return _api.config.queue_defaults()
    except Exception:
        return {}


def _discover_workflow_actions() -> list[str]:
    actions = _api.config.planning.get("planning", {}).get("workflow_actions", {})
    return list(actions.keys())


def _discover_workflow_action(name: str) -> dict[str, Any]:
    try:
        return _api.config.workflow_action(name)
    except Exception:
        return {}


def _discover_kind_aliases() -> dict[str, str]:
    return _api.config.kind_aliases()


def _discover_guidance_levels() -> list[str]:
    try:
        return list(_api.config.guidance_levels().keys())
    except Exception:
        return []


def _discover_default_guidance() -> str:
    try:
        return _api.config.default_guidance()
    except Exception:
        return ""


def _discover_default_profile() -> str:
    try:
        return _api.config.planning.get("planning", {}).get("default_profile", "")
    except Exception:
        return ""


def _discover_dirs() -> dict[str, str]:
    return _api.config.planning.get("planning", {}).get("dirs", {})


def _discover_naming() -> dict[str, Any]:
    return _api.config.planning.get("planning", {}).get("naming", {})


def _discover_conventions() -> dict[str, Any]:
    return _api.config.conventions()


def _discover_base_required_fields() -> list[str]:
    return _api.config.planning.get("planning", {}).get("base_required_fields", [])


def _discover_base_optional_fields() -> list[str]:
    return _api.config.planning.get("planning", {}).get("base_optional_fields", [])


# ---------------------------------------------------------------------------
# Tool generators — wrap API calls with introspected metadata
# ---------------------------------------------------------------------------


def _build_tool_descriptions() -> dict[str, str]:
    """Build human-readable descriptions for each tool from API metadata."""
    kinds = _discover_kinds()
    actions = _discover_lifecycle_actions()
    profiles = _discover_creation_profiles()
    ref_fields = _discover_all_reference_fields()
    default_ref = _discover_default_reference_field()
    ref_field_info = {f: _discover_reference_field_info(f) for f in ref_fields}
    workflow_actions = _discover_workflow_actions()
    guidance_levels = _discover_guidance_levels()
    default_guidance = _discover_default_guidance()
    default_profile = _discover_default_profile()
    aliases = _discover_kind_aliases()
    naming = _discover_naming()
    dirs = _discover_dirs()
    conventions = _discover_conventions()

    desc = {}

    # tm_config — discovery tool
    desc["tm_config"] = (
        "Get a snapshot of the entire planning configuration.\n"
        f"Kinds: {kinds}\n"
        f"Kind aliases: {aliases}\n"
        f"Default reference field: {default_ref}\n"
        f"Reference fields: {ref_fields}\n"
        f"Lifecycle actions: {actions}\n"
        f"Creation profiles: {profiles}\n"
        f"Workflow actions: {workflow_actions}\n"
        f"Guidance levels: {guidance_levels}\n"
        f"Default guidance: {default_guidance}\n"
        f"Default profile: {default_profile}\n"
        f"Naming: {naming}\n"
        f"Dirs: {dirs}\n"
        f"Conventions: {conventions}"
    )

    # tm_docs — config discovery
    desc["tm_docs"] = (
        "Access documentation and configuration surfaces.\n"
        "Operations: config (read planning config), surfaces (list doc surfaces), "
        "references (list reference docs), profiles (list request profiles), "
        "profile (get profile by id), support (list support docs), "
        "sync_req (doc sync requirements), pending (pending doc updates), "
        "config (read-only planning config discovery)"
    )

    # tm_list — list items
    desc["tm_list"] = (
        "List planning items. Supports filtering by kind, state, domain, and text search.\n"
        f"Available kinds: {kinds}\n"
        f"Default kind: {_discover_queue_defaults().get('kind', 'N/A')}\n"
        f"Default state: {_discover_queue_defaults().get('state', 'N/A')}\n"
        "Use arrays for multiple values: kind=['task','wp'], state=['ready','in_progress']\n"
        "Use query for text search within item content.\n"
        "Set include_deleted=True to include soft-deleted items.\n"
        "Set include_archived=True to include archived items.\n"
        "Set include_superseded=True to include superseded items."
    )

    # tm_create — create item
    desc["tm_create"] = (
        "Create a planning item. Use tm_docs(op='config') first to discover supported kinds, "
        "required refs, and required fields.\n"
        f"Available kinds: {kinds}\n"
        f"Default profile: {default_profile}\n"
        f"Guidance levels: {guidance_levels}\n"
        f"Default guidance: {default_guidance}"
    )

    # tm_get — get item
    desc["tm_get"] = (
        "Get a planning item. Use depth=head for existence/state checks (cheapest), "
        "depth=meta for frontmatter only, depth=full for metadata+body, "
        "depth=body for raw markdown body (most tokens)."
    )

    # tm_update — update item
    desc["tm_update"] = "Update label, summary, or append text to a planning item's body."

    # tm_state — change state
    desc["tm_state"] = (
        "Change the state of a planning item.\n"
        f"Available lifecycle actions: {actions}\n"
        "States are discovered per kind via tm_docs(op='config')."
    )

    # tm_move — move item
    desc["tm_move"] = "Move a planning item to a different domain."

    # tm_delete — delete item
    desc["tm_delete"] = (
        "Delete a planning item. Soft delete is the default; "
        "hard=True removes the file permanently."
    )

    # tm_relink — relink
    desc["tm_relink"] = (
        "Update a reference/link field in a planning item.\n"
        f"Available reference fields: {ref_fields}\n"
        f"Default reference field: {default_ref}"
    )

    # tm_refs — get refs
    desc["tm_refs"] = (
        f"Get effective references for a planning item.\nAvailable reference fields: {ref_fields}"
    )

    # tm_claim — claim
    desc["tm_claim"] = "Claim ownership of a planning item for multi-agent coordination."

    # tm_unclaim — unclaim
    desc["tm_unclaim"] = "Release ownership of a planning item."

    # tm_claims — list claims
    desc["tm_claims"] = "List active claims on planning items."

    # tm_next — next items
    desc["tm_next"] = (
        "Get the next unclaimed items from the work queue.\n"
        f"Default kind: {_discover_queue_defaults().get('kind', 'N/A')}\n"
        f"Default state: {_discover_queue_defaults().get('state', 'N/A')}"
    )

    # tm_edit — batch edit
    desc["tm_edit"] = (
        "Execute atomic operations on a planning item.\n"
        "Operations: state, label, summary, section, content, meta, field\n"
        "Modes: set, append, replace, add, remove\n"
        "Use one tm_edit call instead of multiple separate calls."
    )

    # tm_section — section operations
    desc["tm_section"] = (
        "Read or write a named section in a planning document.\n"
        "Operations: get, set, append, get_sub (subsection via dot notation)"
    )

    # tm_validate — validate
    desc["tm_validate"] = "Validate all planning documents against schemas and rules."

    # tm_index — rebuild indexes
    desc["tm_index"] = "Rebuild planning indexes."

    # tm_clean_indexes — clean indexes
    desc["tm_clean_indexes"] = (
        "Clear and rebuild planning indexes only (cheaper than full maintain)."
    )

    # tm_maintain — full maintain
    desc["tm_maintain"] = "Full canonical maintenance: reconcile + rebuild derived state."

    # tm_compact — compact IDs
    desc["tm_compact"] = (
        "Compact all planning item IDs to remove sequence gaps. "
        "Renumbers items per kind, rewrites cross-references, renames files, updates counters."
    )

    # tm_reconcile — reconcile
    desc["tm_reconcile"] = "Reconcile planning state with filesystem."

    # tm_events — events
    desc["tm_events"] = "Get recent planning events from the event log."

    # tm_workflow_action — workflow action
    desc["tm_workflow_action"] = (
        f"Run a configured workflow action.\nAvailable actions: {workflow_actions}"
    )

    # tm_dump — dump
    desc["tm_dump"] = "Dump all planning items to a directory."

    # tm_sync_counters — sync counters
    desc["tm_sync_counters"] = "Seed ID counters from existing docs."

    # tm_profiles — creation profiles
    desc["tm_profiles"] = f"List or get creation profiles.\nAvailable profiles: {profiles}"

    # tm_doc_surfaces — doc surfaces
    desc["tm_doc_surfaces"] = "List all documentation surfaces."

    # tm_reference_docs — reference docs
    desc["tm_reference_docs"] = "List all reference documentation files."

    # tm_support_docs — support docs
    desc["tm_support_docs"] = "List supporting documentation."

    # tm_check_sensitive — sensitive data
    desc["tm_check_sensitive"] = (
        "Check a planning item for sensitive data patterns (API keys, tokens, passwords) in body content."
    )

    # tm_guidance — guidance levels
    desc["tm_guidance"] = (
        "Get guidance level details.\n"
        f"Available levels: {guidance_levels}\n"
        f"Default: {default_guidance}"
    )

    # tm_state_transitions — state transitions
    desc["tm_state_transitions"] = (
        f"Get valid state transitions for a kind.\nAvailable kinds: {kinds}"
    )

    # tm_reference_field_info — ref field info
    desc["tm_reference_field_info"] = (
        f"Get information about a reference field.\nAvailable fields: {ref_fields}"
    )

    # tm_kind_config — kind-specific config
    desc["tm_kind_config"] = f"Get configuration for a specific kind.\nAvailable kinds: {kinds}"

    # tm_kind_aliases — kind name aliases
    desc["tm_kind_aliases"] = f"Get kind name aliases.\nKind mapping: {aliases}"

    # tm_all_reference_fields — all reference fields
    desc["tm_all_reference_fields"] = (
        f"Get all reference fields and their info.\nAvailable fields: {ref_fields}"
    )

    # tm_dirs — directory paths
    desc["tm_dirs"] = "Get configured directory paths for planning items."

    # tm_naming — naming rules
    desc["tm_naming"] = "Get configured naming rules for planning items."

    # tm_conventions — conventions
    desc["tm_conventions"] = "Get configured conventions for planning items."

    return desc


_DESCRIPTIONS = _build_tool_descriptions()


# ---------------------------------------------------------------------------
# Tool implementations — thin wrappers around API calls
# ---------------------------------------------------------------------------


@_mcp.tool(description=_DESCRIPTIONS["tm_config"])
def tm_config() -> dict[str, Any]:
    """Get a snapshot of the entire planning configuration."""
    kinds = _discover_kinds()
    actions = _discover_lifecycle_actions()
    profiles = _discover_creation_profiles()
    ref_fields = _discover_all_reference_fields()
    return {
        "kinds": kinds,
        "kind_aliases": _discover_kind_aliases(),
        "default_reference_field": _discover_default_reference_field(),
        "reference_fields": ref_fields,
        "lifecycle_actions": actions,
        "creation_profiles": profiles,
        "workflow_actions": _discover_workflow_actions(),
        "guidance_levels": _discover_guidance_levels(),
        "default_guidance": _discover_default_guidance(),
        "default_profile": _discover_default_profile(),
        "naming": _discover_naming(),
        "dirs": _discover_dirs(),
        "conventions": _discover_conventions(),
    }


@_mcp.tool(description=_DESCRIPTIONS["tm_docs"])
def tm_docs(
    op: str,
    id: str | None = None,
    role: str | None = None,
    mode: str = "compact",
    profile_pack: str | None = None,
) -> dict[str, Any]:
    """Access documentation and configuration surfaces."""
    if op == "config":
        return {
            "kinds": _discover_kinds(),
            "kind_aliases": _discover_kind_aliases(),
            "default_reference_field": _discover_default_reference_field(),
            "reference_fields": _discover_all_reference_fields(),
            "lifecycle_actions": _discover_lifecycle_actions(),
            "creation_profiles": _discover_creation_profiles(),
            "workflow_actions": _discover_workflow_actions(),
            "guidance_levels": _discover_guidance_levels(),
            "default_guidance": _discover_default_guidance(),
            "default_profile": _discover_default_profile(),
            "queue_defaults": _discover_queue_defaults(),
            "dirs": _discover_dirs(),
            "naming": _discover_naming(),
            "conventions": _discover_conventions(),
            "base_required_fields": _discover_base_required_fields(),
            "base_optional_fields": _discover_base_optional_fields(),
        }
    if op == "surfaces":
        return _api.extracts._docs_manager().list_surfaces()
    if op == "references":
        return _api.extracts._docs_manager().list_collection("references")
    if op == "profiles":
        return _discover_creation_profiles()
    if op == "profile":
        if not id:
            return {"error": "id is required for profile operation"}
        return _discover_creation_profile(id)
    if op == "support":
        return _api.extracts._docs_manager().list_collection("support", role=role)
    if op == "sync_req":
        if not id:
            return {"error": "kind is required for sync_req operation"}
        return _api.config.doc_sync_requirements(id, profile_pack)
    if op == "pending":
        if not id:
            return {"error": "kind is required for pending operation"}
        return _api.config.pending_doc_updates(id, profile_pack)
    return {"error": f"unknown op: {op}"}


@_mcp.tool(description=_DESCRIPTIONS["tm_list"])
def tm_list(
    kind: str | list[str] | None = None,
    state: str | list[str] | None = None,
    domain: str | None = None,
    query: str | None = None,
    include_deleted: bool = False,
    include_archived: bool = False,
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    """List planning items with filtering."""
    return _api.list(
        kind=kind,
        state=state,
        domain=domain,
        query=query,
        include_deleted=include_deleted,
        include_archived=include_archived,
        include_superseded=include_superseded,
    )


@_mcp.tool(description=_DESCRIPTIONS["tm_create"])
def tm_create(
    kind: str,
    label: str,
    summary: str,
    content: str | None = None,
    source: str | None = None,
    domain: str | None = None,
    workflow: str | None = None,
    refs: dict[str, Any] | None = None,
    fields: dict[str, Any] | None = None,
    check_duplicates: bool = True,
    profile: str | None = None,
    current_understanding: str | None = None,
    open_questions: list[str] | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Create a planning item."""
    if content is not None:
        item = _api.create_with_content(
            kind=kind,
            label=label,
            summary=summary,
            content=content,
            source=source,
            domain=domain,
            workflow=workflow,
            refs=refs,
            fields=fields,
            check_duplicates=check_duplicates,
        )
    else:
        item = _api.new(
            kind=kind,
            label=label,
            summary=summary,
            domain=domain,
            workflow=workflow,
            refs=refs,
            fields=fields,
            profile=profile,
            current_understanding=current_understanding,
            open_questions=open_questions,
            source=source,
            context=context,
            check_duplicates=check_duplicates,
        )
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


@_mcp.tool(description=_DESCRIPTIONS["tm_get"])
def tm_get(
    id: str, depth: str = "full", with_related: bool = False, with_resources: bool = False
) -> dict[str, Any]:
    """Get a planning item."""
    if depth == "head":
        return _api.head(id)
    if depth == "meta":
        return _api.head(id)
    if depth == "body":
        return {"body": _api.get_content(id)}
    return _api.lookup(id)


@_mcp.tool(description=_DESCRIPTIONS["tm_update"])
def tm_update(
    id: str, label: str | None = None, summary: str | None = None, append: str | None = None
) -> dict[str, Any]:
    """Update a planning item."""
    item = _api.update(id, label=label, summary=summary, body_append=append)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


@_mcp.tool(description=_DESCRIPTIONS["tm_state"])
def tm_state(
    id: str, new_state: str, reason: str | None = None, actor: str | None = None
) -> dict[str, Any]:
    """Change the state of a planning item."""
    item = _api.state(id, new_state, reason=reason, actor=actor)
    result = {"id": item.data["id"], "state": item.data["state"]}
    for field in ("archived_at", "archived_by", "archive_reason", "restored_at", "restored_by"):
        if field in item.data:
            result[field] = item.data[field]
    return result


@_mcp.tool(description=_DESCRIPTIONS["tm_move"])
def tm_move(id: str, domain: str) -> dict[str, Any]:
    """Move a planning item to a different domain."""
    item = _api.move(id, domain)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


@_mcp.tool(description=_DESCRIPTIONS["tm_delete"])
def tm_delete(id: str, hard: bool = False, reason: str | None = None) -> dict[str, Any]:
    """Delete a planning item."""
    return _api.delete(id, hard=hard, reason=reason)


@_mcp.tool(description=_DESCRIPTIONS["tm_relink"])
def tm_relink(
    src: str, field: str, dst: str, seq: int | None = None, display: str | None = None
) -> dict[str, Any]:
    """Update a reference/link field in a planning item."""
    item = _api.relink(src, field, dst, seq=seq, display=display)
    return {"id": item.data["id"], "field": field}


@_mcp.tool(description=_DESCRIPTIONS["tm_refs"])
def tm_refs(id: str, field: str | None = None) -> list[str]:
    """Get effective references for a planning item."""
    return _api.effective_refs(id, field=field)


@_mcp.tool(description=_DESCRIPTIONS["tm_claim"])
def tm_claim(kind: str, id: str, holder: str, ttl: int | None = None) -> dict[str, Any]:
    """Claim ownership of a planning item."""
    return _api.claim(kind, id, holder, ttl)


@_mcp.tool(description=_DESCRIPTIONS["tm_unclaim"])
def tm_unclaim(id: str) -> bool:
    """Release ownership of a planning item."""
    return _api.unclaim(id)


@_mcp.tool(description=_DESCRIPTIONS["tm_claims"])
def tm_claims(kind: str | None = None) -> list[dict[str, Any]]:
    """List active claims on planning items."""
    return _api.claims(kind)


@_mcp.tool(description=_DESCRIPTIONS["tm_next"])
def tm_next(
    kind: str | None = None, state: str | None = None, domain: str | None = None
) -> list[dict[str, Any]]:
    """Get the next unclaimed items from the work queue."""
    defaults = _discover_queue_defaults()
    return _api.next_items(
        kind=kind or defaults.get("kind"),
        state=state or defaults.get("state"),
        domain=domain,
    )


@_mcp.tool(description=_DESCRIPTIONS["tm_edit"])
def tm_edit(id: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Execute atomic operations on a planning item."""
    from src.audiagentic.planning.fs.read import parse_markdown
    from src.audiagentic.planning.fs.write import dump_markdown

    if not id or "/" in id or "\\" in id or ".." in id:
        return {"error": f"Invalid ID '{id}': path separators or '..' are not allowed"}

    item = _api._find(id)
    results = []
    errors = []

    try:
        for i, op in enumerate(operations):
            op_type = op.get("op") or op.get("operation")
            if op_type == "state":
                _api.state(id, op["value"])
                results.append({"index": i, "op": "state", "success": True})
            elif op_type == "label":
                _api.update(id, label=op["value"])
                results.append({"index": i, "op": "label", "success": True})
            elif op_type == "summary":
                _api.update(id, summary=op["value"])
                results.append({"index": i, "op": "summary", "success": True})
            elif op_type == "section":
                name = op["name"]
                content = op["content"]
                mode = op.get("mode", "set")
                lines = _api.get_content(id).splitlines()
                start, end = _find_section(lines, name, level=1)
                if start is None:
                    heading = name.replace("_", " ").title()
                    new_content = (
                        _api.get_content(id).rstrip()
                        + f"\n\n# {heading}\n\n"
                        + content.strip()
                        + "\n"
                    )
                else:
                    old = "\n".join(lines[start:end]).strip()
                    new_body = (
                        (old + "\n\n" + content.strip()).strip()
                        if mode == "append" and old
                        else content.strip()
                    )
                    new_lines = lines[:start] + ([new_body] if new_body else []) + lines[end:]
                    new_content = "\n".join(new_lines).rstrip() + "\n"
                _api.update_content(id, new_content, mode="replace")
                results.append({"index": i, "op": "section", "name": name, "success": True})
            elif op_type == "content":
                mode = op.get("mode", "replace")
                _api.update_content(id, op["value"], mode=mode)
                results.append({"index": i, "op": "content", "success": True})
            elif op_type == "meta":
                from tools.planning.fs.read import parse_markdown
                from tools.planning.fs.write import dump_markdown

                data, body = parse_markdown(item.path)
                if "meta" not in data:
                    data["meta"] = {}
                data["meta"][op["field"]] = op["value"]
                dump_markdown(item.path, data, body)
                _api.index()
                results.append({"index": i, "op": "meta", "field": op["field"], "success": True})
            elif op_type == "field":
                data, body = parse_markdown(item.path)
                field_shape = _api.config.reference_field_shape(op["field"])
                is_rel_list = field_shape == "rel_list"
                if op.get("mode", "set") in {"set", "replace"}:
                    data[op["field"]] = op.get("value")
                else:
                    vals = list(data.get(op["field"], []) or [])
                    targets = op.get("value")
                    if targets is None:
                        targets = []
                    if not isinstance(targets, list):
                        targets = [targets]
                    if is_rel_list:
                        if op.get("mode") == "add":
                            for t in targets:
                                if not isinstance(t, dict) or t.get("ref") not in [
                                    v.get("ref") for v in vals if isinstance(v, dict)
                                ]:
                                    vals.append(t)
                        elif op.get("mode") == "remove":
                            target_keys = {
                                t.get("ref") if isinstance(t, dict) else t for t in targets
                            }
                            vals = [
                                v
                                for v in vals
                                if (v.get("ref") if isinstance(v, dict) else v) not in target_keys
                            ]
                    else:
                        if op.get("mode") == "add":
                            for t in targets:
                                if t not in vals:
                                    vals.append(t)
                        elif op.get("mode") == "remove":
                            vals = [v for v in vals if v not in targets]
                    data[op["field"]] = vals
                dump_markdown(item.path, data, body)
                results.append({"index": i, "op": "field", "field": op["field"], "success": True})
            else:
                errors.append({"index": i, "op": op_type, "error": f"unknown op: {op_type}"})

        _api.index()
        return {"id": id, "operations_executed": len(results), "results": results, "errors": errors}

    except Exception as e:
        return {"id": id, "error": str(e), "results": results, "errors": errors}


@_mcp.tool(description=_DESCRIPTIONS["tm_section"])
def tm_section(id: str, op: str, section: str, content: str | None = None) -> dict[str, Any]:
    """Read or write a named section in a planning document."""
    if op == "get":
        try:
            text = _api.get_content(id)
            lines = text.splitlines()
            start, end = _find_section(lines, section, level=1)
            if start is None:
                return {"id": id, "section": section, "content": "", "found": False}
            return {
                "id": id,
                "section": section,
                "content": "\n".join(lines[start:end]).strip(),
                "found": True,
            }
        except Exception as e:
            return {"error": str(e)}
    if op in {"set", "append"}:
        try:
            text = _api.get_content(id)
            lines = text.splitlines()
            start, end = _find_section(lines, section, level=1)
            if start is None:
                heading = section.replace("_", " ").title()
                new_text = text.rstrip() + f"\n\n# {heading}\n\n" + (content or "").strip() + "\n"
            else:
                old = "\n".join(lines[start:end]).strip()
                new_body = (
                    (old + "\n\n" + (content or "").strip()).strip()
                    if op == "append" and old
                    else (content or "").strip()
                )
                new_lines = lines[:start] + ([new_body] if new_body else []) + lines[end:]
                new_text = "\n".join(new_lines).rstrip() + "\n"
            _api.update_content(id, new_text, mode="replace")
            return {"id": id}
        except Exception as e:
            return {"error": str(e)}
    if op == "get_sub":
        try:
            parts = _split_section_path(section)
            if not parts:
                return {"id": id, "section_path": section, "content": "", "found": False}
            current_text = _api.get_content(id)
            current_lines = current_text.splitlines()
            first_start, first_end = _find_section(current_lines, parts[0], level=1)
            if first_start is None:
                return {"id": id, "section_path": section, "content": "", "found": False}
            text = "\n".join(current_lines[first_start:first_end]).strip()
            if len(parts) == 1:
                return {"id": id, "section_path": section, "content": text, "found": True}
            for target_raw in parts[1:]:
                found = False
                for level in range(2, 7):
                    s, e = _find_section(text.splitlines(), target_raw, level=level)
                    if s is not None:
                        text = "\n".join(text.splitlines()[s:e]).strip()
                        found = True
                        break
                if not found:
                    return {"id": id, "section_path": section, "content": "", "found": False}
            return {"id": id, "section_path": section, "content": text, "found": True}
        except Exception as e:
            return {"error": str(e)}
    return {"error": f"unknown op: {op}"}


@_mcp.tool(description=_DESCRIPTIONS["tm_validate"])
def tm_validate() -> dict[str, Any]:
    """Validate all planning documents."""
    errs = _api.validate()
    return {"ok": not errs, "errors": errs}


@_mcp.tool(description=_DESCRIPTIONS["tm_index"])
def tm_index() -> dict[str, Any]:
    """Rebuild planning indexes."""
    _api.index()
    return {"ok": True}


@_mcp.tool(description=_DESCRIPTIONS["tm_clean_indexes"])
def tm_clean_indexes() -> dict[str, Any]:
    """Clear and rebuild planning indexes only."""
    return _api.clean_indexes()


@_mcp.tool(description=_DESCRIPTIONS["tm_maintain"])
def tm_maintain() -> dict[str, Any]:
    """Full canonical maintenance."""
    return _api.maintain()


@_mcp.tool(description=_DESCRIPTIONS["tm_compact"])
def tm_compact() -> dict[str, Any]:
    """Compact planning item IDs."""
    return _api.compact()


@_mcp.tool(description=_DESCRIPTIONS["tm_reconcile"])
def tm_reconcile() -> dict[str, Any]:
    """Reconcile planning state with filesystem."""
    return _api.reconcile()


@_mcp.tool(description=_DESCRIPTIONS["tm_events"])
def tm_events(tail: int = 20) -> list[dict[str, Any]]:
    """Get recent planning events."""
    return _api.event_service.events(tail=tail)


@_mcp.tool(description=_DESCRIPTIONS["tm_workflow_action"])
def tm_workflow_action(action_name: str, context: dict[str, Any]) -> dict[str, Any]:
    """Run a configured workflow action."""
    result = _api.run_workflow_action(action_name, context)
    return {
        key: {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}
        for key, item in result.items()
    }


@_mcp.tool(description=_DESCRIPTIONS["tm_dump"])
def tm_dump(output_dir: str | None = None, format_: str = "json") -> dict[str, Any]:
    """Dump all planning items."""
    return _api.dump_all(output_dir=output_dir, format_=format_)


@_mcp.tool(description=_DESCRIPTIONS["tm_sync_counters"])
def tm_sync_counters() -> dict[str, Any]:
    """Seed ID counters from existing docs."""
    _api.sync_id_counters()
    return {"ok": True}


@_mcp.tool(description=_DESCRIPTIONS["tm_profiles"])
def tm_profiles(name: str | None = None) -> dict[str, Any]:
    """List or get creation profiles."""
    if name:
        return _discover_creation_profile(name)
    return _discover_creation_profiles()


@_mcp.tool(description=_DESCRIPTIONS["tm_doc_surfaces"])
def tm_doc_surfaces() -> list[dict[str, Any]]:
    """List all documentation surfaces."""
    try:
        mgr = _api.extracts._docs_manager()
        return [s.__dict__ for s in mgr.list_surfaces()]
    except Exception as e:
        return {"error": str(e)}


@_mcp.tool(description=_DESCRIPTIONS["tm_reference_docs"])
def tm_reference_docs() -> list[dict[str, str]]:
    """List all reference documentation files."""
    try:
        mgr = _api.extracts._docs_manager()
        return mgr.list_collection("references")
    except Exception as e:
        return {"error": str(e)}


@_mcp.tool(description=_DESCRIPTIONS["tm_support_docs"])
def tm_support_docs(id: str | None = None, role: str | None = None) -> list[dict[str, Any]]:
    """List supporting documentation."""
    try:
        mgr = _api.extracts._docs_manager()
        return mgr.list_collection("support", supports_id=id, role=role)
    except Exception as e:
        return {"error": str(e)}


@_mcp.tool(description=_DESCRIPTIONS["tm_check_sensitive"])
def tm_check_sensitive(id: str) -> dict[str, Any]:
    """Check a planning item for sensitive data patterns."""
    from tools.planning.tm_helper import check_sensitive_data

    return check_sensitive_data(id)


@_mcp.tool(description=_DESCRIPTIONS["tm_guidance"])
def tm_guidance(name: str | None = None) -> dict[str, Any]:
    """Get guidance level details."""
    if name:
        try:
            return _api.config.guidance_for(name)
        except Exception:
            return {"error": f"unknown guidance level: {name}"}
    return {
        "levels": _discover_guidance_levels(),
        "default": _discover_default_guidance(),
    }


@_mcp.tool(description=_DESCRIPTIONS["tm_state_transitions"])
def tm_state_transitions(kind: str, workflow: str | None = None) -> dict[str, Any]:
    """Get valid state transitions for a kind."""
    try:
        initial = _discover_initial_states(kind, workflow)
        active = _discover_active_states(kind, workflow)
        blocked = _discover_blocked_states(kind, workflow)
        complete = _discover_complete_states(kind, workflow)
        terminal = _discover_terminal_states(kind, workflow)
        return {
            "kind": kind,
            "workflow": workflow or _api.config.default_workflow_name(kind),
            "initial": initial,
            "active": active,
            "blocked": blocked,
            "complete": complete,
            "terminal": terminal,
            "actions": _discover_lifecycle_actions(),
        }
    except Exception as e:
        return {"error": str(e)}


@_mcp.tool(description=_DESCRIPTIONS["tm_reference_field_info"])
def tm_reference_field_info(field: str) -> dict[str, Any]:
    """Get information about a reference field."""
    try:
        info = _discover_reference_field_info(field)
        return {"field": field, "shape": info["shape"], "targets": info["targets"]}
    except Exception as e:
        return {"error": str(e)}


@_mcp.tool(description=_DESCRIPTIONS["tm_kind_config"])
def tm_kind_config(kind: str) -> dict[str, Any]:
    """Get configuration for a specific kind."""
    try:
        cfg = _discover_kind_config(kind)
        ref_fields = _discover_reference_fields(kind)
        states = _discover_states(kind)
        return {
            "kind": kind,
            "config": cfg,
            "reference_fields": ref_fields,
            "states": states,
        }
    except Exception as e:
        return {"error": str(e)}


@_mcp.tool(description=_DESCRIPTIONS["tm_kind_aliases"])
def tm_kind_aliases() -> dict[str, str]:
    """Get kind name aliases."""
    return _discover_kind_aliases()


@_mcp.tool(description=_DESCRIPTIONS["tm_all_reference_fields"])
def tm_all_reference_fields() -> dict[str, Any]:
    """Get all reference fields and their info."""
    fields = _discover_all_reference_fields()
    return {
        "fields": fields,
        "field_info": {f: _discover_reference_field_info(f) for f in fields},
    }


@_mcp.tool(description=_DESCRIPTIONS["tm_dirs"])
def tm_dirs() -> dict[str, Any]:
    """Get configured directory paths."""
    return _discover_dirs()


@_mcp.tool(description=_DESCRIPTIONS["tm_naming"])
def tm_naming() -> dict[str, Any]:
    """Get configured naming rules."""
    return _discover_naming()


@_mcp.tool(description=_DESCRIPTIONS["tm_conventions"])
def tm_conventions() -> dict[str, Any]:
    """Get configured conventions."""
    return _discover_conventions()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    _mcp.run()
