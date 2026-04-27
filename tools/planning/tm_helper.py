#!/usr/bin/env python3
"""Thin planning helper with config-driven documentation support."""

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
_current_root = None  # Override for set_root()
_api = None  # Lazy API instance
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.api import PlanningAPI
from audiagentic.planning.app.config import Config
from audiagentic.planning.app.docs_mgr import DocumentationManager
from audiagentic.planning.app.section_registry import split_section_path
from audiagentic.planning.fs.read import parse_markdown
from audiagentic.planning.fs.write import dump_markdown


def _validate_id(id_: str) -> None:
    """Prevent path traversal by ensuring ID contains no path separators or dot-dot.

    Raises:
        ValueError: If ID is potentially malicious.
    """
    if not id_:
        raise ValueError("ID cannot be empty")
    if "/" in id_ or "\\" in id_ or ".." in id_:
        raise ValueError(f"Invalid ID '{id_}': path separators or '..' are not allowed")


def _get_root() -> Path:
    """Get the current project root.

    Returns:
        Project root path (auto-detected or explicitly set)
    """
    return _current_root or _ROOT


def _get_api(test_mode: bool = False) -> PlanningAPI:
    """Get or create the PlanningAPI instance for the current root.

    Args:
        test_mode: If True, use test directory structure

    Returns:
        PlanningAPI instance
    """
    global _api
    if _api is None:
        _api = PlanningAPI(_get_root(), test_mode=test_mode)
    return _api


def set_root(root: Path) -> None:
    """Set the project root for all subsequent operations.

    Args:
        root: Project root path

    Usage:
        tm.set_root(Path("/path/to/project"))
        task = tm.create("task", "Label", "Summary", refs={"spec": "spec-0001"})
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


def set_test_mode(enabled: bool = True) -> None:
    """Enable or disable test mode for all subsequent operations.

    When test mode is enabled, planning artifacts are created in a separate
    test directory structure (docs/planning/test/) to avoid polluting
    the primary planning directory.

    Args:
        enabled: If True, enable test mode; if False, disable test mode

    Usage:
        tm.set_test_mode()  # Enable test mode
        tm.set_test_mode(False)  # Disable test mode
    """
    global _api
    _api = PlanningAPI(_get_root(), test_mode=enabled)


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
    """Execute a batch of operations atomically with backup/restore.

    Supported operations:
    - state: {"op": "state", "value": "new_state"}
    - label: {"op": "label", "value": "new_label"}
    - summary: {"op": "summary", "value": "new_summary"}
    - section: {"op": "section", "name": "section_name", "content": "...", "mode": "set|append"}
    - content: {"op": "content", "value": "...", "mode": "replace|append"}
    - meta: {"op": "meta", "field": "key", "value": "val"}
    - field: {"op": "field", "field": "spec_refs", "mode": "add|remove|replace|set", "value": "spec-123"}
    """
    _validate_id(id_)
    item = api._find(id_)
    backup_path = item.path.with_suffix(".bak")
    backup_created = False

    results = []
    errors = []

    try:
        # Create backup of the original file
        import shutil

        shutil.copy2(item.path, backup_path)
        backup_created = True

        for i, op in enumerate(operations):
            op_type = op.get("op") or op.get("operation")
            try:
                if op_type == "state":
                    value = op["value"]
                    api.state(id_, value)
                    results.append({"index": i, "op": "state", "success": True, "value": value})

                elif op_type == "label":
                    value = op["value"]
                    api.update(id_, label=value)
                    results.append({"index": i, "op": "label", "success": True, "value": value})

                elif op_type == "summary":
                    value = op["value"]
                    api.update(id_, summary=value)
                    results.append({"index": i, "op": "summary", "success": True, "value": value})

                elif op_type == "section":
                    name = op["name"]
                    content = op["content"]
                    mode = op.get("mode", "set")  # set or append
                    # Get current content and modify section
                    current = api.get_content(id_)
                    if mode == "append":
                        new_content = _replace_section_body(current, name, content, append=True)
                    else:
                        new_content = _replace_section_body(current, name, content, append=False)
                    api.update_content(id_, new_content, mode="replace")
                    results.append({"index": i, "op": "section", "name": name, "success": True})

                elif op_type == "content":
                    value = op["value"]
                    mode = op.get("mode", "replace")
                    api.update_content(id_, value, mode=mode)
                    results.append({"index": i, "op": "content", "success": True})

                elif op_type == "meta":
                    field = op["field"]
                    value = op["value"]
                    # Update meta field in frontmatter
                    item_curr = api._find(id_)
                    data, body = parse_markdown(item_curr.path)
                    if "meta" not in data:
                        data["meta"] = {}
                    data["meta"][field] = value
                    dump_markdown(item_curr.path, data, body)
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

                elif op_type == "field":
                    field = op["field"]
                    value = op.get("value")
                    mode = op.get("mode", "set")
                    item_curr = api._find(id_)
                    data, body = parse_markdown(item_curr.path)
                    _apply_frontmatter_field_op(api, data, field, mode, value)
                    dump_markdown(item_curr.path, data, body)
                    results.append(
                        {
                            "index": i,
                            "op": "field",
                            "field": field,
                            "mode": mode,
                            "success": True,
                            "value": value,
                        }
                    )

                else:
                    raise ValueError(f"Unknown operation type: {op_type}")

            except Exception as e:
                errors.append({"index": i, "op": op_type, "error": str(e)})
                raise  # Trigger backup restore

        # Re-index after successful batch
        api.index()

        # Clean up backup
        if backup_created:
            backup_path.unlink(missing_ok=True)

        return {
            "id": id_,
            "batch": True,
            "operations_executed": len(results),
            "results": results,
            "errors": [],
        }

    except Exception as e:
        # Restore backup on failure
        if backup_created:
            import shutil

            shutil.move(str(backup_path), str(item.path))

        return {
            "id": id_,
            "batch": True,
            "success": False,
            "error": str(e),
            "results": results,
            "errors": errors,
        }


def _apply_frontmatter_field_op(
    api: PlanningAPI,
    data: dict[str, Any],
    field: str,
    mode: str,
    value: Any,
) -> None:
    """Apply add/remove/replace/set to a top-level frontmatter field.

    Supported shapes:
    - scalar reference fields
    - list[str] reference fields
    - list[dict] relationship fields where each entry contains at minimum `ref`
    """
    field_shape = api.config.reference_field_shape(field)
    is_relationship_list = field_shape == "rel_list"

    if mode in {"set", "replace"}:
        data[field] = value
        return

    current = data.get(field)

    if current is None:
        if mode == "add":
            if is_relationship_list:
                current = []
            else:
                current = []
            data[field] = current
        elif mode == "remove":
            return

    if not isinstance(data.get(field), list):
        raise ValueError(f"field '{field}' is not a list; use mode='set' for scalar fields")

    if is_relationship_list:
        _apply_relationship_list_op(data, field, mode, value)
    else:
        _apply_scalar_list_op(data, field, mode, value)


def _normalize_values(value: Any) -> list[Any]:
    """Normalize operation value to list for add/remove on list-shaped fields."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _apply_scalar_list_op(data: dict[str, Any], field: str, mode: str, value: Any) -> None:
    """Apply add/remove to list[str] style frontmatter fields."""
    vals = list(data.get(field, []) or [])
    targets = _normalize_values(value)

    if mode == "add":
        for target in targets:
            if target not in vals:
                vals.append(target)
    elif mode == "remove":
        vals = [existing for existing in vals if existing not in targets]
    else:
        raise ValueError(f"unsupported mode '{mode}' for list field '{field}'")

    data[field] = vals


def _ref_key(value: Any) -> Any:
    """Return comparable key for relationship entries."""
    if isinstance(value, dict):
        return value.get("ref")
    return value


def _apply_relationship_list_op(data: dict[str, Any], field: str, mode: str, value: Any) -> None:
    """Apply add/remove to list[dict(ref=...)] relationship fields."""
    vals = list(data.get(field, []) or [])
    targets = _normalize_values(value)
    target_keys = {_ref_key(target) for target in targets}

    if mode == "add":
        existing_keys = {_ref_key(existing) for existing in vals}
        for target in targets:
            key = _ref_key(target)
            if key in existing_keys:
                continue
            if isinstance(target, dict):
                vals.append(target)
            else:
                vals.append({"ref": target})
            existing_keys.add(key)
    elif mode == "remove":
        vals = [existing for existing in vals if _ref_key(existing) not in target_keys]
    else:
        raise ValueError(f"unsupported mode '{mode}' for relationship field '{field}'")

    data[field] = vals


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
    domain: str | None = None,
    workflow: str | None = None,
    refs: dict[str, object] | None = None,
    fields: dict[str, object] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Create a new planning document with initial content.

    Args:
        kind: Configured item kind
        label: Item label
        summary: Item summary
        content: Initial markdown content
        source: Optional provenance/source for request creation
        domain: Optional item domain
        workflow: Optional workflow ID
        refs: Create refs keyed by configured creation sources
        fields: Extra frontmatter fields
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
        workflow=workflow,
        refs=refs,
        fields=fields,
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


def group(
    parent: str,
    items: list[str],
    label: str,
    summary: str,
    domain: str | None = None,
    action: str = "group",
    root: Path | None = None,
) -> dict[str, Any]:
    """Run a configured grouping workflow action.

    Args:
        parent: Parent item ID
        items: Child item IDs
        label: Group label
        summary: Group summary
        domain: Optional domain
        action: Configured workflow action name
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    result = api.run_workflow_action(
        action,
        {
            "parent_id": parent,
            "item_ids": items,
            "label": label,
            "summary": summary,
            "domain": domain,
        },
    )
    if len(result) != 1:
        return {
            "items": [
                {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}
                for item in result.values()
            ]
        }
    item = next(iter(result.values()))
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}


def run_workflow_action(
    action: str, context: dict[str, Any], root: Path | None = None
) -> dict[str, Any]:
    """Run a configured workflow action by name."""
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    result = api.run_workflow_action(action, context)
    return {
        key: {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}
        for key, item in result.items()
    }


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


def create(
    kind: str,
    label: str,
    summary: str,
    content: str | None = None,
    source: str | None = None,
    domain: str | None = None,
    workflow: str | None = None,
    refs: dict[str, object] | None = None,
    fields: dict[str, object] | None = None,
    check_duplicates: bool = True,
    profile: str | None = None,
    current_understanding: str | None = None,
    open_questions: list[str] | None = None,
    context: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Generic create helper backed by live planning config.

    Args:
        kind: Configured item kind.
        refs: Create refs keyed by planning.creation.seed_reference_fields sources.
        fields: Extra frontmatter fields.
        root: Optional project root.

    Returns:
        Dict with id and path
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)

    if content is not None:
        item = api.create_with_content(
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
        item = api.new(
            kind,
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
    return {"id": item.data["id"], "path": str(item.path.relative_to(project_root))}
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

    Runs full canonical maintenance: filename reconciliation + derived state rebuild.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        Reconciliation result with renames and orphans.
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.reconcile()


def clean_indexes(root: Path | None = None) -> dict[str, Any]:
    """Clear and rebuild planning indexes only.

    Cheaper than full reconcile/maintain. Does not touch filenames or extracts.
    Use when lookup state is stale but planning docs are known-good.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        Dict with indexes_rebuilt status.
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.clean_indexes()


def compact(root: Path | None = None) -> dict[str, Any]:
    """Compact all planning item IDs to remove sequence gaps.

    Deterministic, non-AI operation. Renumbers all items sequentially (kind-1, kind-2, ...)
    per kind, rewrites all cross-references, renames files, and updates counters.

    After compaction, runs full validate. Items that cannot be auto-repaired are returned
    in the ``cannot_repair`` list for human or AI review.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        Report with remap table, rename log, updated counters, and cannot_repair list.
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.compact()


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
    kind: str | list[str] | None = None,
    root: Path | None = None,
    include_deleted: bool = False,
    include_archived: bool = False,
    include_superseded: bool = False,
    state: str | list[str] | None = None,
) -> list[dict[str, Any]]:
    """List planning items, optionally filtered by kind and state.

    Args:
        kind: Optional kind filter (request, spec, plan, task, wp, standard). Can be a single kind or list of kinds.
        root: Optional project root. If None, uses current root.
        include_deleted: Include deleted items
        include_archived: Include archived items
        include_superseded: Include superseded items (default: excluded)
        state: Filter by state (captured, distilled, in_progress, ready, done, archive, etc.). Can be a single state or list of states.

    Returns:
        List of item summaries
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    items = api._scan()

    # Normalize kind to list
    kind_list = [kind] if isinstance(kind, str) else kind if kind else None
    if kind_list:
        items = [i for i in items if i.kind in kind_list]

    if not include_deleted:
        items = [i for i in items if not api.config.is_soft_deleted(i.data)]
    archive_state = api.config.lifecycle_action_state("archive")
    supersede_state = api.config.lifecycle_action_state("supersede")
    if not include_archived and archive_state:
        items = [i for i in items if i.data.get("state") != archive_state]
    if not include_superseded and supersede_state:
        items = [i for i in items if i.data.get("state") != supersede_state]

    # Normalize state to list
    state_list = [state] if isinstance(state, str) else state if state else None
    if state_list:
        items = [i for i in items if i.data.get("state") in state_list]

    return [
        {
            "id": i.data["id"],
            "kind": i.kind,
            "label": i.data["label"],
            "state": i.data["state"],
            "deleted": api.config.is_soft_deleted(i.data),
            "archived": i.data.get("state") == archive_state,
            "superseded": i.data.get("state") == supersede_state,
        }
        for i in items
    ]


def next_items(
    kind: str | list[str] | None = None,
    state: str | list[str] | None = None,
    domain: str | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """List items of a given kind in a given state.

    Args:
        kind: Item kind. Defaults come from planning.queue_defaults.
        state: Item state. Defaults come from planning.queue_defaults.
        domain: Optional domain filter
        root: Optional project root. If None, uses current root.

    Returns:
        List of next items
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.next_items(kind, state, domain)


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


def effective_refs(
    id_: str, field: str | None = None, root: Path | None = None
) -> list[str]:
    """List effective reference values for a planning item.

    Args:
        id_: Item ID
        field: Reference field to resolve. If None, uses configured default_reference_field.
        root: Optional project root. If None, uses current root.

    Returns:
        List of referenced item IDs
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root)
    return api.effective_refs(id_, field=field)


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


def status(root: Path | None = None, test_mode: bool = False) -> dict[str, Any]:
    """Get summary counts of all planning items grouped by kind and state.

    Args:
        root: Optional project root. If None, uses current root.
        test_mode: If True, include test artifacts in counts

    Returns:
        Status summary dict with counts per kind per state
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root, test_mode=test_mode)
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


def list_test_artifacts(root: Path | None = None) -> list[dict[str, Any]]:
    """List all test artifacts in the planning system.

    Args:
        root: Optional project root. If None, uses current root.

    Returns:
        List of test artifact summaries
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root, test_mode=True)
    items = api._scan()
    return [
        {
            "id": i.data["id"],
            "kind": i.kind,
            "label": i.data["label"],
            "state": i.data["state"],
            "path": str(i.path.relative_to(project_root)),
        }
        for i in items
    ]


def delete_test_artifacts(
    ids: list[str], reason: str = "Test artifact cleanup", root: Path | None = None
) -> list[dict[str, Any]]:
    """Delete multiple test artifacts.

    Args:
        ids: List of artifact IDs to delete
        reason: Deletion reason
        root: Optional project root. If None, uses current root.

    Returns:
        List of deletion results
    """
    project_root = root or _get_root()
    api = PlanningAPI(project_root, test_mode=True)
    results = []
    for id_ in ids:
        result = api.delete(id_, hard=False, reason=reason)
        results.append(result)
    return results


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
    return _docs_manager(project_root).list_collection("references")


def list_creation_profiles(root: Path | None = None) -> list[dict[str, Any]]:
    """List all creation profiles.

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


def get_creation_profile(profile_id: str, root: Path | None = None) -> dict[str, Any] | None:
    """Get a creation profile by ID.

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
    return _docs_manager(project_root).list_collection(
        "support",
        supports_id=supports_id,
        role=role,
    )


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


def _replace_section_body(text: str, section: str, content: str, append: bool = False) -> str:
    lines = text.splitlines()
    start, end = _find_section(lines, section, level=1)

    if start is None:
        # Section doesn't exist; create it
        heading = section.replace("_", " ").title()
        return text.rstrip() + f"\n\n# {heading}\n\n" + content.strip() + "\n"

    old = "\n".join(lines[start:end]).strip()
    new_body = (old + "\n\n" + content.strip()).strip() if append and old else content.strip()
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


def set_section(id_: str, section: str, content: str, root: Path | None = None) -> dict[str, Any]:
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
        _replace_section_body(get_content(id_, project_root), section, content, append=False),
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
        _replace_section_body(get_content(id_, project_root), section, content, append=True),
        mode="replace",
        root=project_root,
    )


def get_subsection(id_: str, section_path: str, root: Path | None = None) -> dict[str, Any]:
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


def _validate_profile_pack(profile_pack: str | None, root: Path | None = None) -> None:
    """Validate that a profile pack exists and is loadable.

    Args:
        profile_pack: Profile pack name
        root: Optional project root. If None, uses current root.

    Raises:
        ValueError: If profile pack doesn't exist or is invalid
    """
    if not profile_pack:
        raise ValueError("profile_pack is required")
    project_root = root or _get_root()
    path = project_root / f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
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
    kind: str, profile_pack: str | None, root: Path | None = None
) -> dict[str, Any]:
    """Get documentation sync requirements for a kind and profile pack.

    Args:
        kind: Work kind (task, wp, etc.)
        profile_pack: Profile pack name
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
        "required_updates": _docs_manager(project_root).pending_updates_for_kind(kind, pp),
        "all_required_updates": _docs_manager(project_root).profile_pack_required_updates(pp),
    }


def pending_doc_updates(
    kind: str, profile_pack: str | None, root: Path | None = None
) -> list[str]:
    """List pending documentation updates for a kind and profile pack.

    Args:
        kind: Work kind (task, wp, etc.)
        profile_pack: Profile pack name
        root: Optional project root. If None, uses current root.

    Returns:
        List of required documentation updates
    """
    project_root = root or _get_root()
    _validate_profile_pack(profile_pack, project_root)
    cfg = _load_yaml(
        project_root, f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
    )
    return _docs_manager(project_root).pending_updates_for_kind(kind, cfg.get("profile_pack", {}))


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
    return _verify_structure_impl(root)

    return {"id": id_, "section_path": section_path, "content": text, "found": True}


def get_doc_sync_requirements(
    kind: str, profile_pack: str | None, root: Path | None = None
) -> dict[str, Any]:
    """Get documentation sync requirements for a kind and profile pack.

    Args:
        kind: Work kind (task, wp, etc.)
        profile_pack: Profile pack name
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
        "required_updates": _docs_manager(project_root).pending_updates_for_kind(kind, pp),
        "all_required_updates": _docs_manager(project_root).profile_pack_required_updates(pp),
    }


def pending_doc_updates(
    kind: str, profile_pack: str | None, root: Path | None = None
) -> list[str]:
    """List pending documentation updates for a kind and profile pack.

    Args:
        kind: Work kind (task, wp, etc.)
        profile_pack: Profile pack name
        root: Optional project root. If None, uses current root.

    Returns:
        List of required documentation updates
    """
    project_root = root or _get_root()
    _validate_profile_pack(profile_pack, project_root)
    cfg = _load_yaml(
        project_root, f".audiagentic/planning/config/profile-packs/{profile_pack}.yaml"
    )
    return _docs_manager(project_root).pending_updates_for_kind(kind, cfg.get("profile_pack", {}))


def _verify_structure_impl(root: Path | None = None) -> dict[str, Any]:
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
        ".audiagentic/planning/meta",
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
        k for k, v in checks.items() if v.get("required", False) and not v.get("ok", False)
    ]
    optional_failures = [
        k for k, v in checks.items() if not v.get("required", False) and not v.get("ok", False)
    ]
    healthy = len(required_failures) == 0

    if required_failures:
        summary = f"Structure check FAILED: {len(required_failures)} required check(s) failed - {', '.join(required_failures)}."
        if optional_failures:
            summary += f" ({len(optional_failures)} optional checks also missing)"
    elif optional_failures:
        summary = f"Structure check OK: {len(optional_failures)} optional extension(s) not installed - {', '.join(optional_failures)}"
    else:
        summary = "Structure check PASSED: planning module is healthy and fully equipped"

    return {
        "root": str(project_root),
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
            warnings.append(f"Possible {pattern_name.replace('_', ' ')} detected in body")

    return {
        "id": id_,
        "has_sensitive_data": len(warnings) > 0,
        "warnings": warnings,
        "patterns_checked": list(_SENSITIVE_PATTERNS.keys()),
    }


def delete(
    id_: str, hard: bool = False, reason: str | None = None, root: Path | None = None
) -> dict[str, Any]:
    """Delete a planning item.

    Args:
        id_: Item ID to delete
        hard: If True, remove file; if False, soft-delete
        reason: Optional deletion reason
        root: Optional project root

    Returns:
        Dict with id and deleted status
    """
    api = _get_api()
    return api.delete(id_, hard=hard, reason=reason)


def planning_config_summary(
    mode: str = "compact",
    kind: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return live planning config in agent-friendly form.

    Compact mode (default) — low token, cacheable per session:
      - default_profile, default_guidance
      - per-kind: has_domain, required_fields, optional_fields, required_refs,
        required_sections, state_on_create, usage hint
      - available profiles (names only) and guidance levels (names only)

    Full mode — deeper detail on request:
      - everything in compact plus relationship rules, workflow defaults,
        standard defaults, template section names

    Args:
        mode: "compact" or "full"
        kind: Optional kind filter. If given, returns single-kind dict.
        root: Optional project root. If None, uses current root.

    Returns:
        Structured dict suitable for agent consumption.
    """
    project_root = root or _get_root()
    cfg = Config(project_root)

    kinds = cfg.all_kinds()
    if kind is not None:
        if kind not in kinds:
            raise ValueError(f"Unknown kind: {kind!r}. Available: {kinds}")
        kinds = [kind]

    def _kind_entry(k: str) -> dict[str, Any]:
        kc = cfg.kind_config(k)
        wf = cfg.workflow_for(k)
        entry: dict[str, Any] = {
            "has_domain": cfg.kind_has_domain(k),
            "required_fields": cfg.required_fields(k),
            "optional_fields": cfg.optional_fields(k),
            "required_refs": cfg.kind_required_refs(k),
            "required_sections": cfg.required_sections(k) or [],
            "state_on_create": cfg.initial_state(k),
            "usage": (
                f"tm_create(kind='{k}'"
                + (", domain='<domain>'" if cfg.kind_has_domain(k) else "")
                + (
                    ", refs={"
                    + ", ".join(f"'{r}': '<id>'" for r in cfg.kind_required_refs(k))
                    + "}"
                    if cfg.kind_required_refs(k)
                    else ""
                )
                + ", label='...')"
            ),
        }
        if mode == "full":
            entry["relationship_rules"] = cfg.relationship_rules(k)
            entry["workflow_states"] = list(wf.get("states", {}).keys())
            entry["default_references"] = cfg.profiles.get("planning", {}).get(
                "default_references", {}
            ).get(k, {})
            template = cfg.document_template(k)
            import re as _re
            entry["template_sections"] = _re.findall(r"^## (.+)$", template, _re.MULTILINE)
        return entry

    profiles = cfg.profiles.get("planning", {}).get("profiles", {})
    guidance_levels = cfg.guidance_levels()

    out: dict[str, Any] = {
        "default_profile": cfg.default_profile(),
        "default_guidance": cfg.default_guidance(),
        "kinds": {k: _kind_entry(k) for k in kinds},
        "profiles": list(profiles.keys()),
        "guidance_levels": list(guidance_levels.keys()),
    }

    if mode == "full":
        out["profiles_detail"] = {
            name: {k: v for k, v in data.items() if k not in ("on_request_create",)}
            for name, data in profiles.items()
            if isinstance(data, dict)
        }
        out["guidance_levels_detail"] = guidance_levels

    return out
