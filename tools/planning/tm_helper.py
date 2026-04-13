#!/usr/bin/env python3
"""Thin planning helper with documentation-surface support.

Support docs are surfaced here as structured sidecar docs rather than core
planning kinds in this phase.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
import yaml


def _find_project_root() -> Path:
    """Find AUDiaGentic project root containing .audiagentic/planning/.

    Search strategy:
    1. Check current working directory and all parents for .audiagentic/planning
    2. Check module directory parents as fallback
    3. Raise error if not found

    Returns:
        Path to project root

    Raises:
        RuntimeError: If project root cannot be determined
    """
    override = os.environ.get("AUDIAGENTIC_ROOT")
    if override:
        override_path = Path(override).resolve()
        if (override_path / ".audiagentic" / "planning").exists():
            return override_path
        raise RuntimeError(
            f"AUDIAGENTIC_ROOT={override_path} does not contain .audiagentic/planning/"
        )

    # Strategy 1: Search from cwd upward
    for p in [Path.cwd(), *Path.cwd().parents]:
        if (p / ".audiagentic" / "planning").exists():
            return p

    # Strategy 2: Search from module location upward
    module_dir = Path(__file__).resolve().parent
    for p in [module_dir, *module_dir.parents]:
        if (p / ".audiagentic" / "planning").exists():
            return p

    # Strategy 3: Last resort - check typical locations
    # This handles the case where we're in tools/planning/ relative to root
    likely_root = module_dir.parent.parent.parent
    if (likely_root / ".audiagentic" / "planning").exists():
        return likely_root

    raise RuntimeError(
        f"Could not find project root with .audiagentic/planning/. "
        f"Searched from cwd={Path.cwd()} and module={module_dir}"
    )


_ROOT = _find_project_root()
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.api import PlanningAPI
from audiagentic.planning.app.docs_mgr import DocumentationManager
from audiagentic.planning.app.refs_mgr import ReferencesManager
from audiagentic.planning.app.support_mgr import SupportingDocsManager
from audiagentic.planning.app.section_registry import split_section_path
from audiagentic.planning.fs.read import parse_markdown
from audiagentic.planning.fs.write import dump_markdown

# Module-level root - can be overridden for isolated operations
_current_root: Path | None = None
_api: PlanningAPI | None = None


def _get_root() -> Path:
    """Get the current project root.

    Returns:
        Project root path (auto-detected or explicitly set)
    """
    return _current_root or _ROOT


def _get_api() -> PlanningAPI:
    """Get or create the PlanningAPI instance for the current root.

    Returns:
        PlanningAPI instance
    """
    global _api
    if _api is None:
        _api = PlanningAPI(_get_root())
    return _api


def set_root(root: Path) -> None:
    """Set the project root for all subsequent operations.

    Args:
        root: Project root path

    Usage:
        tm.set_root(Path("/path/to/project"))
        task = tm.new_task("Label", "Summary", "spec-0001")
    """
    global _current_root, _api
    _current_root = root
    _api = PlanningAPI(root)


def reset_root() -> None:
    """Reset to auto-detected project root.

    Usage:
        tm.reset_root()
    """
    global _current_root, _api
    _current_root = None
    _api = PlanningAPI(_ROOT)


def update_task_status(
    id_: str,
    state: str,
    notes: str,
    section: str = "description",
    root: Path | None = None,
) -> dict[str, Any]:
    """Update task state and append implementation notes in a single call.

    This is a convenience wrapper that combines state transition with documentation
    updates, making it more efficient than separate state() and append_section() calls.

    Args:
        id_: Task ID to update
        state: New state value (draft, ready, in_progress, done)
        notes: Implementation notes to append
        section: Section to append notes to (default: description)
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id, state, and path

    Usage:
        tm.update_task_status("task-0001", "done", "All implementation complete:\\n- Item 1\\n- Item 2")
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)

    # Update state
    item = api.state(id_, state)

    # Append notes to specified section
    notes_content = f"\n\n**Status: {state.upper()}**\n\n{notes}"
    append_section(id_, section, notes_content, project_root)

    return {
        "id": item.data["id"],
        "state": item.data["state"],
        "path": str(item.path.relative_to(project_root)),
    }


def _load_yaml(root: Path, path: str) -> dict[str, Any]:
    """Load YAML file relative to root.

    Args:
        root: Project root path
        path: Relative path to YAML file

    Returns:
        Parsed YAML content as dict
    """
    full_path = root / path
    if not full_path.exists():
        return {}
    return yaml.safe_load(full_path.read_text(encoding="utf-8")) or {}


def _docs_manager(root: Path | None = None) -> DocumentationManager:
    """Get documentation manager for current or specified root.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        DocumentationManager instance
    """
    project_root = root or _get_root()
    cfg = _load_yaml(project_root, ".audiagentic/planning/config/documentation.yaml")
    return DocumentationManager(project_root, cfg)


def new_request(
    label: str,
    summary: str,
    source: str,
    profile: str | None = None,
    guidance: str | None = None,
    current_understanding: str | None = None,
    open_questions: list[str] | None = None,
    context: str | None = None,
    root: Path | None = None,
    check_duplicates: bool = True,
) -> dict[str, Any]:
    """Create a new Request planning document with optional duplicate detection.

    Args:
        label: Request label
        summary: Request summary
        source: Identifier of the agent or user who created this request (e.g., 'claude', 'codex',
            'user@example.com'). MUST be a creator identifier, not a process description.
        profile: Optional request profile such as feature or issue.
        guidance: Optional guidance level (light, standard, deep). Defaults to project default.
        current_understanding: Optional initial understanding text.
        open_questions: Optional initial open-question list.
        context: Optional extra context for where this request came from.
        root: Optional project root. If None, uses current root.
        check_duplicates: If True, check for existing requests with same label/summary

    Returns:
        Dict with id, path, and created flag (False if duplicate found)
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)

    # Apply default profile if not specified
    if profile is None:
        profile = api.config.default_profile()

    # Validate profile
    profiles = api.config.profile_for(profile)
    if not profiles:
        raise ValueError(
            f"Invalid profile '{profile}'. Must be one of: {list(api.config.profiles.get('planning', {}).get('profiles', {}).keys())}"
        )

    # Apply default guidance if not specified
    if guidance is None:
        guidance = api.config.default_guidance()

    # Validate guidance level
    levels = api.config.guidance_levels()
    if guidance not in levels:
        raise ValueError(
            f"Invalid guidance level '{guidance}'. Must be one of: {list(levels.keys())}"
        )

    if check_duplicates:
        existing = [i for i in api._scan() if i.kind == "request"]
        label_lower = label.lower().strip()

        for item in existing:
            existing_label = item.data.get("label", "").lower().strip()
            if existing_label == label_lower:
                return {
                    "id": item.data["id"],
                    "path": str(item.path.relative_to(project_root)),
                    "created": False,
                    "duplicate_of": item.data["id"],
                    "message": f"Request already exists: {item.data['id']}",
                }

    item = api.new(
        "request",
        label=label,
        summary=summary,
        profile=profile,
        guidance=guidance,
        current_understanding=current_understanding,
        open_questions=open_questions,
        source=source,
        context=context,
        check_duplicates=check_duplicates,
    )
    return {
        "id": item.data["id"],
        "path": str(item.path.relative_to(project_root)),
        "created": True,
    }


def new_spec(
    label: str,
    summary: str,
    request_refs: list[str] | None = None,
    root: Path | None = None,
    check_duplicates: bool = True,
) -> dict[str, Any]:
    """Create a new Specification planning document with optional duplicate detection.

    Args:
        label: Spec label
        summary: Spec summary
        request_refs: Required list of request IDs to reference
        root: Optional project root. If None, uses current root.
        check_duplicates: If True, check for existing specs with same label/summary

    Returns:
        Dict with id, path, and created flag (False if duplicate found)
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)

    if check_duplicates:
        existing = [i for i in api._scan() if i.kind == "spec"]
        label_lower = label.lower().strip()

        for item in existing:
            existing_label = item.data.get("label", "").lower().strip()
            if existing_label == label_lower:
                return {
                    "id": item.data["id"],
                    "path": str(item.path.relative_to(project_root)),
                    "created": False,
                    "duplicate_of": item.data["id"],
                    "message": f"Specification already exists: {item.data['id']}",
                }

    item = api.new(
        "spec",
        label=label,
        summary=summary,
        request_refs=request_refs,
        check_duplicates=check_duplicates,
    )
    return {
        "id": item.data["id"],
        "path": str(item.path.relative_to(project_root)),
        "created": True,
    }


def _validate_reference(ref_id: str, ref_type: str, root: Path | None = None) -> None:
    """Validate that a referenced planning item exists.

    Args:
        ref_id: Planning item ID to validate
        ref_type: Type of reference (e.g., 'spec', 'plan') for error message
        root: Optional project root. If None, uses current root.

    Raises:
        ValueError: If reference does not exist
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    try:
        api._find(ref_id)
    except KeyError:
        raise ValueError(f"{ref_type} '{ref_id}' does not exist")


def new_plan(
    label: str,
    summary: str,
    spec: str | None = None,
    request_refs: list[str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Create a new Plan planning document.

    Args:
        label: Plan label
        summary: Plan summary
        spec: Optional spec ID to link
        request_refs: Optional request IDs to link for traceability.
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    if spec:
        _validate_reference(spec, "spec", project_root)
    for req_id in request_refs or []:
        _validate_reference(req_id, "request", project_root)
    api = PlanningAPI(project_root)
    item = api.new(
        "plan",
        label=label,
        summary=summary,
        spec=spec,
        request_refs=request_refs,
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def new_task(
    label: str,
    summary: str,
    spec: str,
    domain: str = "core",
    target: str | None = None,
    parent: str | None = None,
    workflow: str | None = None,
    request_refs: list[str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Create a new Task planning document.

    Args:
        label: Task label
        summary: Task summary
        spec: Spec ID (required)
        domain: Task domain (default: core)
        target: Optional target ID
        parent: Optional parent ID
        workflow: Optional workflow ID
        request_refs: Optional request IDs to link for traceability.
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    _validate_reference(spec, "spec", project_root)
    if parent:
        _validate_reference(parent, "parent", project_root)
    for req_id in request_refs or []:
        _validate_reference(req_id, "request", project_root)
    api = PlanningAPI(project_root)
    item = api.new(
        "task",
        label=label,
        summary=summary,
        spec=spec,
        domain=domain,
        target=target,
        parent=parent,
        workflow=workflow,
        request_refs=request_refs,
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def new_wp(
    label: str,
    summary: str,
    plan: str,
    domain: str = "core",
    workflow: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Create a new WorkPackage planning document.

    Args:
        label: WP label
        summary: WP summary
        plan: Plan ID (required)
        domain: WP domain (default: core)
        workflow: Optional workflow ID
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    _validate_reference(plan, "plan", project_root)
    api = PlanningAPI(project_root)
    item = api.new(
        "wp", label=label, summary=summary, plan=plan, domain=domain, workflow=workflow
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def new_standard(label: str, summary: str, root: Path | None = None) -> dict[str, Any]:
    """Create a new Standard planning document.

    Args:
        label: Standard label
        summary: Standard summary
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    item = api.new("standard", label=label, summary=summary)
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def state(
    id_: str,
    new_state: str,
    reason: str | None = None,
    actor: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Change the state of a planning item.

    Args:
        id_: Item ID
        new_state: New state value
        reason: Optional archive reason for archive transitions
        actor: Optional actor identifier for archive/restore metadata
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and state
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    item = api.state(id_, new_state, reason=reason, actor=actor)
    result = {"id": item.data["id"], "state": item.data["state"]}
    for field in (
        "archived_at",
        "archived_by",
        "archive_reason",
        "restored_at",
        "restored_by",
    ):
        if field in item.data:
            result[field] = item.data[field]
    return result


def move(id_: str, domain: str, root: Path | None = None) -> dict[str, Any]:
    """Move a planning item to a different domain.

    Args:
        id_: Item ID
        domain: Target domain
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    item = api.move(id_, domain)
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def update(
    id_: str,
    label: str | None = None,
    summary: str | None = None,
    append: str | None = None,
    root: Path | None = None,
    operations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Update label, summary, or body text of a planning item, or execute batch operations.

    Args:
        id_: Item ID
        label: Optional new label
        summary: Optional new summary
        append: Optional text to append to body
        root: Optional project root. If None, uses current root.
        operations: Optional list of operations for batch updates. If provided, executes
                   all operations atomically. Supported ops: state, label, summary, section,
                   content, meta. Example: [{"op": "state", "value": "done"},
                   {"op": "section", "name": "Notes", "content": "..."}]

    Returns:
        Dict with id, path, and results (if batch)
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)

    if operations:
        return _execute_batch_operations(api, id_, operations)

    item = api.update(id_, label=label, summary=summary, body_append=append)
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def _execute_batch_operations(
    api: PlanningAPI, id_: str, operations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Execute a batch of operations atomically.

    Supported operations:
    - state: {"op": "state", "value": "new_state"}
    - label: {"op": "label", "value": "new_label"}
    - summary: {"op": "summary", "value": "new_summary"}
    - section: {"op": "section", "name": "section_name", "content": "...", "mode": "set|append"}
    - content: {"op": "content", "value": "...", "mode": "replace|append"}
    - meta: {"op": "meta", "field": "key", "value": "val"}
    """
    results = []
    errors = []

    try:
        for i, op in enumerate(operations):
            op_type = op.get("op") or op.get("operation")
            try:
                if op_type == "state":
                    value = op["value"]
                    api.state(id_, value)
                    results.append(
                        {"index": i, "op": "state", "success": True, "value": value}
                    )

                elif op_type == "label":
                    value = op["value"]
                    api.update(id_, label=value)
                    results.append(
                        {"index": i, "op": "label", "success": True, "value": value}
                    )

                elif op_type == "summary":
                    value = op["value"]
                    api.update(id_, summary=value)
                    results.append(
                        {"index": i, "op": "summary", "success": True, "value": value}
                    )

                elif op_type == "section":
                    name = op["name"]
                    content = op["content"]
                    mode = op.get("mode", "set")  # set or append
                    # Get current content and modify section
                    current = api.get_content(id_)
                    if mode == "append":
                        new_content = _replace_section_body(
                            current, name, content, append=True
                        )
                    else:
                        new_content = _replace_section_body(
                            current, name, content, append=False
                        )
                    api.update_content(id_, new_content, mode="replace")
                    results.append(
                        {"index": i, "op": "section", "name": name, "success": True}
                    )

                elif op_type == "content":
                    value = op["value"]
                    mode = op.get("mode", "replace")
                    api.update_content(id_, value, mode=mode)
                    results.append({"index": i, "op": "content", "success": True})

                elif op_type == "meta":
                    field = op["field"]
                    value = op["value"]
                    # Update meta field in frontmatter
                    item = api._find(id_)
                    data, body = parse_markdown(item.path)
                    if "meta" not in data:
                        data["meta"] = {}
                    data["meta"][field] = value
                    dump_markdown(item.path, data, body)
                    api.index()
                    results.append(
                        {
                            "index": i,
                            "op": "meta",
                            "field": field,
                            "success": True,
                            "value": value,
                        }
                    )

                else:
                    raise ValueError(f"Unknown operation type: {op_type}")

            except Exception as e:
                errors.append({"index": i, "op": op_type, "error": str(e)})
                raise  # Stop on first error for atomicity

        # Re-index after successful batch
        api.index()

        return {
            "id": id_,
            "batch": True,
            "operations_executed": len(results),
            "results": results,
            "errors": [],
        }

    except Exception as e:
        return {
            "id": id_,
            "batch": True,
            "success": False,
            "error": str(e),
            "results": results,
            "errors": errors,
        }


def get_content(id_: str, root: Path | None = None) -> str:
    """Get the full markdown content of a planning document.

    Args:
        id_: Item ID
        root: Optional project root. If None, uses current root.

    Returns:
        Document content as string
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.get_content(id_)


def update_content(
    id_: str,
    content: str,
    mode: str = "replace",
    section: str | None = None,
    position: int | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Update content of a planning document.

    Args:
        id_: Item ID
        content: New content
        mode: Update mode (replace, append, insert)
        section: Optional section name for section-based updates
        position: Optional position for insert mode
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    item = api.update_content(id_, content, mode, section, position)
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def create_with_content(
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
    root: Path | None = None,
) -> dict[str, Any]:
    """Create a new planning document with initial content.

    Args:
        kind: Item kind (request, spec, plan, task, wp, standard)
        label: Item label
        summary: Item summary
        content: Initial markdown content
        source: Optional provenance/source for request creation
        domain: Item domain (default: core)
        spec: Optional spec ID
        plan: Optional plan ID
        parent: Optional parent ID
        target: Optional target ID
        workflow: Optional workflow ID
        request_refs: Optional list of request IDs
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    item = api.create_with_content(
        kind,
        label,
        summary,
        content,
        source=source,
        domain=domain,
        spec=spec,
        plan=plan,
        parent=parent,
        target=target,
        workflow=workflow,
        request_refs=request_refs,
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def relink(
    src: str,
    field: str,
    dst: str,
    seq: int | None = None,
    display: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Update a link field in a planning item.

    Args:
        src: Source item ID
        field: Field to update (spec, plan, parent, etc.)
        dst: Destination item ID
        seq: Optional sequence number
        display: Optional display text
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and field
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    item = api.relink(src, field, dst, seq, display)
    return {"id": item.data["id"], "field": field}


def package(
    plan: str,
    tasks: list[str],
    label: str,
    summary: str,
    domain: str = "core",
    root: Path | None = None,
) -> dict[str, Any]:
    """Group multiple Tasks into a new WorkPackage within a Plan.

    Args:
        plan: Plan ID
        tasks: List of task IDs
        label: WP label
        summary: WP summary
        domain: WP domain (default: core)
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    item = api.package(plan, tasks, label, summary, domain)
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def validate(root: Path | None = None) -> list[str]:
    """Validate all planning documents against schemas and rules.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        List of validation errors
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.validate()


def delete(
    id_: str,
    hard: bool = False,
    reason: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Delete a planning item.

    Soft delete is the default; hard delete removes the file and syncs counters.
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.delete(id_, hard=hard, reason=reason)


def index(root: Path | None = None) -> None:
    """Re-index all planning documents.

    Args:
        root: Optional project root. If None, uses current root.
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    api.index()


def reconcile(root: Path | None = None) -> dict[str, Any]:
    """Reconcile planning state with filesystem.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        Reconciliation result
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.reconcile()


def show(id_: str, root: Path | None = None) -> dict[str, Any]:
    """Get a full view of a planning item with all metadata.

    Args:
        id_: Item ID
        root: Optional project root. If None, uses current root.

    Returns:
        Item metadata and relationships
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.extracts.show(id_)


def head(id_: str, root: Path | None = None) -> dict[str, Any]:
    """Return lean index-only metadata for a planning item."""
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.head(id_)


def extract(
    id_: str,
    with_related: bool = False,
    with_resources: bool = False,
    include_body: bool = True,
    write_to_disk: bool = True,
    root: Path | None = None,
) -> dict[str, Any]:
    """Extract a planning item with optional related items.

    Args:
        id_: Item ID
        with_related: Include related items
        with_resources: Include resource references
        include_body: Include markdown body content
        write_to_disk: Persist extract JSON to disk
        root: Optional project root. If None, uses current root.

    Returns:
        Extracted item data
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.extracts.extract(
        id_,
        with_related,
        with_resources,
        include_body,
        write_to_disk,
    )


def list_kind(
    kind: str | None = None,
    root: Path | None = None,
    include_deleted: bool = False,
    include_archived: bool = False,
    include_superseded: bool = False,
) -> list[dict[str, Any]]:
    """List planning items, optionally filtered by kind.

    Args:
        kind: Optional kind filter (request, spec, plan, task, wp, standard)
        root: Optional project root. If None, uses current root.
        include_deleted: Include deleted items
        include_archived: Include archived items
        include_superseded: Include superseded items (default: excluded)

    Returns:
        List of item summaries
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    items = api._scan()
    if kind:
        items = [i for i in items if i.kind == kind]
    if not include_deleted:
        items = [i for i in items if not i.data.get("deleted")]
    if not include_archived:
        items = [i for i in items if i.data.get("state") != "archived"]
    if not include_superseded:
        items = [i for i in items if i.data.get("state") != "superseded"]
    return [
        {
            "id": i.data["id"],
            "kind": i.kind,
            "label": i.data["label"],
            "state": i.data["state"],
            "deleted": bool(i.data.get("deleted")),
            "archived": i.data.get("state") == "archived",
            "superseded": i.data.get("state") == "superseded",
        }
        for i in items
    ]


def next_items(
    kind: str = "task",
    state: str = "ready",
    domain: str | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """List items of a given kind in a given state.

    Args:
        kind: Item kind (default: task)
        state: Item state (default: ready)
        domain: Optional domain filter
        root: Optional project root. If None, uses current root.

    Returns:
        List of next items
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.next_items(kind, state, domain)


def next_tasks(
    state: str = "ready", domain: str | None = None, root: Path | None = None
) -> list[dict[str, Any]]:
    """List Tasks in a given state.

    Args:
        state: Task state (default: ready)
        domain: Optional domain filter
        root: Optional project root. If None, uses current root.

    Returns:
        List of next tasks
    """
    return next_items("task", state, domain, root)


def claim(
    kind: str, id_: str, holder: str, ttl: int | None = None, root: Path | None = None
) -> dict[str, Any]:
    """Claim ownership of a planning item.

    Args:
        kind: Item kind
        id_: Item ID
        holder: Claim holder identifier
        ttl: Optional TTL in seconds
        root: Optional project root. If None, uses current root.

    Returns:
        Claim result
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.claim(kind, id_, holder, ttl)


def unclaim(id_: str, root: Path | None = None) -> bool:
    """Release ownership of a planning item.

    Args:
        id_: Item ID
        root: Optional project root. If None, uses current root.

    Returns:
        True if unclaimed successfully
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.unclaim(id_)


def claims(kind: str | None = None, root: Path | None = None) -> list[dict[str, Any]]:
    """List active claims on planning items.

    Args:
        kind: Optional kind filter
        root: Optional project root. If None, uses current root.

    Returns:
        List of active claims
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.claims(kind)


def standards(id_: str, root: Path | None = None) -> list[str]:
    """List applicable standards for a planning item.

    Args:
        id_: Item ID
        root: Optional project root. If None, uses current root.

    Returns:
        List of standard IDs
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.standards(id_)


def list_standards(root: Path | None = None) -> list[dict[str, Any]]:
    """List all standard planning documents.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        List of standards
    """
    return list_kind("standard", root=root)


def get_standard(
    standard_id: str,
    with_related: bool = False,
    with_resources: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    """Get a standard planning document with body and metadata.

    Args:
        standard_id: Standard ID
        with_related: Include related items
        with_resources: Include resource references
        root: Optional project root. If None, uses current root.

    Returns:
        Standard data

    Raises:
        ValueError: If the requested item exists but is not a standard
    """
    data = extract(
        standard_id,
        with_related=with_related,
        with_resources=with_resources,
        root=root,
    )
    item = data.get("item", {})
    if item.get("kind") != "standard":
        raise ValueError(f"{standard_id} is not a standard")
    return data


def events(tail: int = 20, root: Path | None = None) -> list[dict[str, Any]]:
    """Get recent planning events from the event log.

    Args:
        tail: Number of recent events to return
        root: Optional project root. If None, uses current root.

    Returns:
        List of event dicts
    """
    project_root = root or _get_root()
    import json

    p = project_root / ".audiagentic/planning/events/events.jsonl"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()[-tail:]
    return [json.loads(x) for x in lines if x.strip()]


def status(root: Path | None = None) -> dict[str, Any]:
    """Get summary counts of all planning items grouped by kind and state.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        Status summary dict with counts per kind per state
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    items = api._scan()
    out: dict[str, dict[str, int]] = {}
    for i in items:
        out.setdefault(i.kind, {})
        out[i.kind].setdefault(i.data["state"], 0)
        out[i.kind][i.data["state"]] += 1
    # Also add total count per kind
    for kind in out:
        out[kind]["_total"] = sum(out[kind].values())
    return out


def list_doc_surfaces(root: Path | None = None) -> list[dict[str, Any]]:
    """List all documentation surfaces.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        List of surface dicts
    """
    project_root = root or _get_root()
    return [s.__dict__ for s in _docs_manager(project_root).list_surfaces()]


def get_doc_surface(surface_id: str, root: Path | None = None) -> dict[str, Any] | None:
    """Get a documentation surface by ID.

    Args:
        surface_id: The surface ID to retrieve
        root: Optional project root. If None, uses current root.

    Returns:
        Surface data dict, or None if not found
    """
    project_root = root or _get_root()
    surface = _docs_manager(project_root).get_surface(surface_id)
    return None if surface is None else surface.__dict__


def list_reference_docs(root: Path | None = None) -> list[dict[str, str]]:
    """List all reference documentation files.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        List of {path, label} dicts for each reference doc
    """
    project_root = root or _get_root()
    return ReferencesManager(project_root).list_reference_docs()


def list_request_profiles(root: Path | None = None) -> list[dict[str, Any]]:
    """List all request profile templates.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        List of profile configs (feature, issue, etc.)
    """
    project_root = root or _get_root()
    cfg = _load_yaml(project_root, ".audiagentic/planning/config/profiles.yaml")
    profiles = cfg.get("planning", {}).get("profiles", {})
    out = []
    for name, data in profiles.items():
        row = {"id": name}
        if isinstance(data, dict):
            row.update(data)
        out.append(row)
    return out


def get_request_profile(
    profile_id: str, root: Path | None = None
) -> dict[str, Any] | None:
    """Get a request profile by ID.

    Args:
        profile_id: The profile ID to retrieve (e.g., 'feature', 'issue')
        root: Optional project root. If None, uses current root.

    Returns:
        Profile data dict with id and config fields, or None if not found
    """
    project_root = root or _get_root()
    cfg = _load_yaml(project_root, ".audiagentic/planning/config/profiles.yaml")
    data = cfg.get("planning", {}).get("profiles", {}).get(profile_id)
    if data is None:
        return None
    row = {"id": profile_id}
    if isinstance(data, dict):
        row.update(data)
    return row


def list_support_docs(
    supports_id: str | None = None, role: str | None = None, root: Path | None = None
) -> list[dict[str, Any]]:
    """List supporting documentation.

    Args:
        supports_id: Optional ID of item to find support docs for
        role: Optional role filter
        root: Optional project root. If None, uses current root.

    Returns:
        List of support doc dicts
    """
    project_root = root or _get_root()
    return SupportingDocsManager(project_root).list_support_docs(supports_id, role)


def _find_section(
    lines: list[str], target_name: str, level: int = 1
) -> tuple[int | None, int | None]:
    """Find a section by name and return (start, end) line indices.

    Args:
        lines: List of markdown lines
        target_name: Section name to find (spaces/underscores normalized)
        level: Heading level to match (1 for #, 2 for ##, etc.)

    Returns:
        (start, end) tuple where start is first line after heading and end is line of next heading.
        Returns (None, None) if section not found.
    """
    target = target_name.replace("_", " ").strip().lower()
    start = None
    end = None
    for i, line in enumerate(lines):
        if line.startswith("#" * level) and not line.startswith("#" * (level + 1)):
            heading = line.lstrip("#").strip().lower()
            if heading == target:
                start = i + 1
                continue
            if start is not None and end is None:
                end = i
                break
    if start is not None and end is None:
        end = len(lines)
    return (start, end) if start is not None else (None, None)


def _replace_section_body(
    text: str, section: str, content: str, append: bool = False
) -> str:
    lines = text.splitlines()
    start, end = _find_section(lines, section, level=1)

    if start is None:
        # Section doesn't exist; create it
        heading = section.replace("_", " ").title()
        return text.rstrip() + f"\n\n# {heading}\n\n" + content.strip() + "\n"

    old = "\n".join(lines[start:end]).strip()
    new_body = (
        (old + "\n\n" + content.strip()).strip() if append and old else content.strip()
    )
    new_lines = lines[:start] + ([new_body] if new_body else []) + lines[end:]
    return "\n".join(new_lines).rstrip() + "\n"


def get_section(id_: str, section: str, root: Path | None = None) -> dict[str, Any]:
    """Get a named section from a planning document.

    Args:
        id_: Item ID
        section: Section name
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id, section, content, and found flag
    """
    project_root = root or _get_root()
    text = get_content(id_, project_root)
    lines = text.splitlines()
    start, end = _find_section(lines, section, level=1)

    if start is None:
        return {"id": id_, "section": section, "content": "", "found": False}

    content = "\n".join(lines[start:end]).strip()
    return {"id": id_, "section": section, "content": content, "found": True}


def set_section(
    id_: str, section: str, content: str, root: Path | None = None
) -> dict[str, Any]:
    """Replace the content of a named section.

    Args:
        id_: Item ID
        section: Section name
        content: New section content
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    return update_content(
        id_,
        _replace_section_body(
            get_content(id_, project_root), section, content, append=False
        ),
        mode="replace",
        root=project_root,
    )


def append_section(
    id_: str, section: str, content: str, root: Path | None = None
) -> dict[str, Any]:
    """Append content to a named section.

    Args:
        id_: Item ID
        section: Section name
        content: Content to append
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    return update_content(
        id_,
        _replace_section_body(
            get_content(id_, project_root), section, content, append=True
        ),
        mode="replace",
        root=project_root,
    )


def get_subsection(
    id_: str, section_path: str, root: Path | None = None
) -> dict[str, Any]:
    """Get nested subsection content using dot or slash notation.

    Supports arbitrary heading levels (doesn't assume sequential ##, ###, etc.).

    Args:
        id_: Planning item ID
        section_path: Subsection path ("section.subsection" or "section/subsection")
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id, section_path, content, and found flag
    """
    project_root = root or _get_root()
    parts = split_section_path(section_path)
    if not parts:
        return {"id": id_, "section_path": section_path, "content": "", "found": False}

    current = get_section(id_, parts[0], project_root)
    if not current.get("found"):
        return {"id": id_, "section_path": section_path, "content": "", "found": False}

    text = current.get("content", "")
    if len(parts) == 1:
        return {"id": id_, "section_path": section_path, "content": text, "found": True}

    lines = text.splitlines()
    for target_raw in parts[1:]:
        found = False
        for level in range(2, 7):
            start, end = _find_section(lines, target_raw, level=level)
            if start is not None:
                text = "\n".join(lines[start:end]).strip()
                lines = text.splitlines()
                found = True
                break

        if not found:
            return {
                "id": id_,
                "section_path": section_path,
                "content": "",
                "found": False,
            }

    return {"id": id_, "section_path": section_path, "content": text, "found": True}


def _validate_profile_pack(profile_pack: str, root: Path | None = None) -> None:
    """Validate that a profile pack exists and is loadable.

    Args:
        profile_pack: Profile pack name
        root: Optional project root. If None, uses current root.

    Raises:
        ValueError: If profile pack doesn't exist or is invalid
    """
    project_root = root or _get_root()
    path = (
        project_root / f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
    )
    if not path.exists():
        raise ValueError(
            f"Profile pack '{profile_pack}' not found at {path}. "
            f"Check .audiagentic/planning/config/profile-packs/ for available packs."
        )
    cfg = _load_yaml(
        project_root, f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
    )
    if "profile_pack" not in cfg:
        raise ValueError(
            f"Profile pack '{profile_pack}' is missing 'profile_pack' key. Check YAML structure."
        )


def get_doc_sync_requirements(
    kind: str, profile_pack: str = "standard", root: Path | None = None
) -> dict[str, Any]:
    """Get documentation sync requirements for a kind and profile pack.

    Args:
        kind: Work kind (task, wp, etc.)
        profile_pack: Profile pack name (default: standard)
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with profile_pack, kind, required_updates, and all_required_updates
    """
    project_root = root or _get_root()
    _validate_profile_pack(profile_pack, project_root)
    cfg = _load_yaml(
        project_root, f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
    )
    pp = cfg.get("profile_pack", {})
    return {
        "profile_pack": profile_pack,
        "kind": kind,
        "required_updates": _docs_manager(project_root).pending_updates_for_kind(
            kind, pp
        ),
        "all_required_updates": _docs_manager(
            project_root
        ).profile_pack_required_updates(pp),
    }


def pending_doc_updates(
    kind: str, profile_pack: str = "standard", root: Path | None = None
) -> list[str]:
    """List pending documentation updates for a kind and profile pack.

    Args:
        kind: Work kind (task, wp, etc.)
        profile_pack: Profile pack name (default: standard)
        root: Optional project root. If None, uses current root.

    Returns:
        List of required documentation updates
    """
    project_root = root or _get_root()
    _validate_profile_pack(profile_pack, project_root)
    cfg = _load_yaml(
        project_root, f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
    )
    return _docs_manager(project_root).pending_updates_for_kind(
        kind, cfg.get("profile_pack", {})
    )


def verify_structure(root: Path | None = None) -> dict[str, Any]:
    """Verify the planning module structure is sound.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        {
            "root": str,
            "healthy": bool,
            "checks": {check_name: {"ok": bool, "required": bool, "message": str}},
            "summary": str
        }
    """
    project_root = root or _get_root()
    checks = {}

    checks["root_exists"] = {
        "ok": project_root.exists(),
        "required": True,
        "message": f"Root directory exists: {project_root}",
    }

    required_dirs = [
        ".audiagentic/planning",
        ".audiagentic/planning/config",
        ".audiagentic/planning/ids",
        ".audiagentic/planning/indexes",
        ".audiagentic/planning/events",
    ]
    for dir_rel in required_dirs:
        dir_path = project_root / dir_rel
        checks[f"dir_{dir_rel.replace('/', '_')}"] = {
            "ok": dir_path.is_dir(),
            "required": True,
            "message": f"Directory exists: {dir_rel}",
        }

    required_configs = [
        ".audiagentic/planning/config/planning.yaml",
        ".audiagentic/planning/config/workflows.yaml",
        ".audiagentic/planning/config/automations.yaml",
        ".audiagentic/planning/config/hooks.yaml",
    ]
    for cfg_rel in required_configs:
        cfg_path = project_root / cfg_rel
        checks[f"config_{cfg_rel.split('/')[-1].replace('.yaml', '')}"] = {
            "ok": cfg_path.is_file(),
            "required": True,
            "message": f"Config file exists: {cfg_rel}",
        }

    optional_configs = [
        ".audiagentic/planning/config/profiles.yaml",
        ".audiagentic/planning/config/documentation.yaml",
    ]
    for cfg_rel in optional_configs:
        cfg_path = project_root / cfg_rel
        checks[f"config_{cfg_rel.split('/')[-1].replace('.yaml', '')}"] = {
            "ok": cfg_path.is_file(),
            "required": False,
            "message": f"Config file exists (optional): {cfg_rel}",
        }

    try:
        api = PlanningAPI(project_root)
        api.validate()
        checks["api_accessible"] = {
            "ok": True,
            "required": True,
            "message": "PlanningAPI is accessible and docs are valid",
        }
    except Exception as e:
        checks["api_accessible"] = {
            "ok": False,
            "required": True,
            "message": f"PlanningAPI error: {e}",
        }

    try:
        api = PlanningAPI(project_root)
        items = api._scan()
        checks["items_scannable"] = {
            "ok": True,
            "required": False,
            "message": f"Found {len(items)} planning items",
        }
    except Exception as e:
        checks["items_scannable"] = {
            "ok": False,
            "required": False,
            "message": f"Scan error: {e}",
        }

    required_failures = [
        k
        for k, v in checks.items()
        if v.get("required", False) and not v.get("ok", False)
    ]
    optional_failures = [
        k
        for k, v in checks.items()
        if not v.get("required", False) and not v.get("ok", False)
    ]
    healthy = len(required_failures) == 0

    if required_failures:
        summary = f"Structure check FAILED: {len(required_failures)} required check(s) failed - {', '.join(required_failures)}."
        if optional_failures:
            summary += f" ({len(optional_failures)} optional checks also missing)"
    elif optional_failures:
        summary = f"Structure check OK: {len(optional_failures)} optional extension(s) not installed - {', '.join(optional_failures)}"
    else:
        summary = (
            "Structure check PASSED: planning module is healthy and fully equipped"
        )

    return {
        "root": str(project_root),
        "healthy": healthy,
        "checks": checks,
        "summary": summary,
    }

    return {"id": id_, "section_path": section_path, "content": text, "found": True}


def get_doc_sync_requirements(
    kind: str, profile_pack: str = "standard", root: Path | None = None
) -> dict[str, Any]:
    """Get documentation sync requirements for a kind and profile pack.

    Args:
        kind: Work kind (task, wp, etc.)
        profile_pack: Profile pack name (default: standard)
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with profile_pack, kind, required_updates, and all_required_updates
    """
    project_root = root or _get_root()
    _validate_profile_pack(profile_pack, project_root)
    cfg = _load_yaml(
        project_root, f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
    )
    pp = cfg.get("profile_pack", {})
    return {
        "profile_pack": profile_pack,
        "kind": kind,
        "required_updates": _docs_manager(project_root).pending_updates_for_kind(
            kind, pp
        ),
        "all_required_updates": _docs_manager(
            project_root
        ).profile_pack_required_updates(pp),
    }


def pending_doc_updates(
    kind: str, profile_pack: str = "standard", root: Path | None = None
) -> list[str]:
    """List pending documentation updates for a kind and profile pack.

    Args:
        kind: Work kind (task, wp, etc.)
        profile_pack: Profile pack name (default: standard)
        root: Optional project root. If None, uses current root.

    Returns:
        List of required documentation updates
    """
    project_root = root or _get_root()
    _validate_profile_pack(profile_pack, project_root)
    cfg = _load_yaml(
        project_root, f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
    )
    return _docs_manager(project_root).pending_updates_for_kind(
        kind, cfg.get("profile_pack", {})
    )


def verify_structure() -> dict[str, Any]:
    """Verify the planning module structure is sound.

    Performs a basic health check on:
    - Required directories (created on init)
    - Required config files (core planning configs)
    - Optional extension configs (request profiles, documentation surfaces)
    - API accessibility and document scanning

    Returns:
        {
            "root": str,
            "healthy": bool,
            "checks": {check_name: {"ok": bool, "required": bool, "message": str}},
            "summary": str
        }
    """
    checks = {}

    # Check root directory
    checks["root_exists"] = {
        "ok": _ROOT.exists(),
        "required": True,
        "message": f"Root directory exists: {_ROOT}",
    }

    # Check required directories (created on baseline_sync)
    required_dirs = [
        ".audiagentic/planning",
        ".audiagentic/planning/config",
        ".audiagentic/planning/ids",
        ".audiagentic/planning/indexes",
        ".audiagentic/planning/events",
    ]
    for dir_rel in required_dirs:
        dir_path = _ROOT / dir_rel
        checks[f"dir_{dir_rel.replace('/', '_')}"] = {
            "ok": dir_path.is_dir(),
            "required": True,
            "message": f"Directory exists: {dir_rel}",
        }

    # Check required config files (core planning)
    required_configs = [
        ".audiagentic/planning/config/planning.yaml",
        ".audiagentic/planning/config/workflows.yaml",
        ".audiagentic/planning/config/automations.yaml",
        ".audiagentic/planning/config/hooks.yaml",
    ]
    for cfg_rel in required_configs:
        cfg_path = _ROOT / cfg_rel
        checks[f"config_{cfg_rel.split('/')[-1].replace('.yaml', '')}"] = {
            "ok": cfg_path.is_file(),
            "required": True,
            "message": f"Config file exists: {cfg_rel}",
        }

    # Check optional extension configs (Phase 2 doc surfaces)
    optional_configs = [
        ".audiagentic/planning/config/profiles.yaml",
        ".audiagentic/planning/config/documentation.yaml",
    ]
    for cfg_rel in optional_configs:
        cfg_path = _ROOT / cfg_rel
        checks[f"config_{cfg_rel.split('/')[-1].replace('.yaml', '')}"] = {
            "ok": cfg_path.is_file(),
            "required": False,
            "message": f"Config file exists (optional): {cfg_rel}",
        }

    # Check API initialization (required for planning functionality)
    try:
        _api.validate()
        checks["api_accessible"] = {
            "ok": True,
            "required": True,
            "message": "PlanningAPI is accessible and docs are valid",
        }
    except Exception as e:
        checks["api_accessible"] = {
            "ok": False,
            "required": True,
            "message": f"PlanningAPI error: {e}",
        }

    # Count existing items (informational only)
    try:
        items = _api._scan()
        checks["items_scannable"] = {
            "ok": True,
            "required": False,
            "message": f"Found {len(items)} planning items",
        }
    except Exception as e:
        checks["items_scannable"] = {
            "ok": False,
            "required": False,
            "message": f"Scan error: {e}",
        }

    # Overall health: only required checks determine healthiness
    required_failures = [
        k
        for k, v in checks.items()
        if v.get("required", False) and not v.get("ok", False)
    ]
    optional_failures = [
        k
        for k, v in checks.items()
        if not v.get("required", False) and not v.get("ok", False)
    ]
    healthy = len(required_failures) == 0

    if required_failures:
        summary = f"Structure check FAILED: {len(required_failures)} required check(s) failed - {', '.join(required_failures)}."
        if optional_failures:
            summary += f" ({len(optional_failures)} optional checks also missing)"
    elif optional_failures:
        summary = f"Structure check OK: {len(optional_failures)} optional extension(s) not installed - {', '.join(optional_failures)}"
    else:
        summary = (
            "Structure check PASSED: planning module is healthy and fully equipped"
        )

    return {
        "root": str(_ROOT),
        "healthy": healthy,
        "checks": checks,
        "summary": summary,
    }


import re

# Sensitive data detection patterns
_SENSITIVE_PATTERNS = {
    "aws_key": r"AKIA[0-9A-Z]{16}",
    "api_key": r'(?:api[_-]?key|apikey)[\s]*[=:]\s*["\']?[a-zA-Z0-9_\-]{20,}["\']?',
    "password": r'(?:password|passwd|pwd)[\s]*[=:]\s*["\']?[^"\'\s]+["\']?',
    "bearer_token": r"Bearer\s+[a-zA-Z0-9\-._~+/]+=*",
}


def check_sensitive_data(id_: str, root: Path | None = None) -> dict[str, Any]:
    """Check a planning item for sensitive data patterns in body content.

    Scans the markdown body for common sensitive patterns:
    - AWS Access Keys (AKIA format)
    - API Keys
    - Passwords
    - Bearer tokens

    Args:
        id_: Planning item ID
        root: Optional project root. If None, uses current root.

    Returns:
        dict with:
        - id: The item being checked
        - has_sensitive_data: True if any patterns matched
        - warnings: List of detected pattern types
        - patterns_checked: List of all pattern names checked

    Example:
        >>> result = check_sensitive_data('task-0123')
        >>> if result['has_sensitive_data']:
        ...     print(f"Found: {result['warnings']}")
    """
    if root:
        set_root(root)

    api = _get_api()

    try:
        item = api.lookup(id_)
    except Exception as e:
        return {
            "id": id_,
            "has_sensitive_data": False,
            "warnings": [f"Error checking item: {str(e)}"],
            "patterns_checked": list(_SENSITIVE_PATTERNS.keys()),
        }

    body = item.body or ""
    warnings = []

    for pattern_name, pattern in _SENSITIVE_PATTERNS.items():
        if re.search(pattern, body, re.IGNORECASE):
            warnings.append(
                f"Possible {pattern_name.replace('_', ' ')} detected in body"
            )

    return {
        "id": id_,
        "has_sensitive_data": len(warnings) > 0,
        "warnings": warnings,
        "patterns_checked": list(_SENSITIVE_PATTERNS.keys()),
    }
