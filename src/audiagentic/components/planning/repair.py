"""Narrow repair for a duplicate active/terminal Planning item identity.

Unlike ordinary edits this tool intentionally works from *verified paths*, because
ambiguous IDs must not be resolved by the normal item lookup. Its sole purpose is
to rekey the active copy without touching the terminal historical record.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from audiagentic.components.planning import (
    durability,
    events,
    item_store,
    planning_paths,
)
from audiagentic.components.planning.identity import (
    validate_item_id,
    validate_plan_slug,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.workflow.frontmatter import parse_frontmatter


@item_store.serialize_planning_collection_write
def rekey_duplicate_active_item(
    project_root: Path,
    plan: str,
    item_id: str,
    new_item_id: str,
) -> dict[str, Any]:
    """Rekey only a duplicated active copy; preserve the terminal one byte-for-byte.

    Refuse unrelated or corrupt records, target collisions and linked reviews.
    The move is journaled as one recoverable write+delete transaction.
    """
    validate_plan_slug(plan)
    validate_item_id(item_id)
    validate_item_id(new_item_id)
    if item_id == new_item_id:
        raise AudiaGenticError(
            code="VAL-PLN-036",
            kind="validation",
            message="replacement identity must differ from the duplicate",
        )

    active_dir = planning_paths.plans_active_dir(project_root)
    terminal_dir = planning_paths.plans_completed_dir(project_root)
    source = planning_paths.assert_contained(
        active_dir, active_dir / plan / f"{item_id}.md"
    )
    historical = planning_paths.assert_contained(
        terminal_dir, terminal_dir / plan / f"{item_id}.md"
    )
    target = planning_paths.assert_contained(
        active_dir, active_dir / plan / f"{new_item_id}.md"
    )
    if not source.is_file() or not historical.is_file():
        raise AudiaGenticError(
            code="VAL-PLN-036",
            kind="validation",
            message="rekey requires both an active and a terminal copy in the same group",
        )
    all_matches = [
        path
        for directory in (active_dir, terminal_dir)
        for path in directory.glob(f"*/{item_id}.md")
    ]
    if set(all_matches) != {source, historical}:
        raise AudiaGenticError(
            code="VAL-PLN-036",
            kind="validation",
            message="duplicate identity has an unexpected placement or extra copy",
        )
    active_fm, body = parse_frontmatter(source.read_text(encoding="utf-8"))
    terminal_original = historical.read_bytes()
    terminal_fm, _ = parse_frontmatter(terminal_original.decode("utf-8"))
    item_store.validate_record_path(source, active_fm, "item")
    item_store.validate_record_path(historical, terminal_fm, "item")
    if active_fm["state"] not in item_store.active_states("item"):
        raise AudiaGenticError(
            code="VAL-PLN-036",
            kind="validation",
            message="source is not an active planning item",
        )
    if terminal_fm["state"] not in item_store.terminal_states("item"):
        raise AudiaGenticError(
            code="VAL-PLN-036",
            kind="validation",
            message="historical copy is not terminal",
        )
    if item_store.find_item(project_root, new_item_id) is not None or target.exists():
        raise AudiaGenticError(
            code="VAL-PLN-005",
            kind="validation",
            message="replacement item identity is already allocated",
        )
    if item_store.review_paths(project_root, item_id):
        raise AudiaGenticError(
            code="VAL-PLN-037",
            kind="validation",
            message="cannot rekey a duplicate with linked reviews",
        )

    active_fm["id"] = new_item_id
    explanation = (
        f"Active record rekeyed from {item_id} to {new_item_id} because an "
        f"independently completed {item_id} already occupies the original identity. "
        f"The historical record is retained unchanged. The active scope remains "
        f"unaccepted and must be reconciled against completed evidence before implementation."
    )
    if "## Change Log\n" in body:
        body = body.replace(
            "## Change Log\n",
            f"## Identity reconciliation\n\n{explanation}\n\n## Change Log\n",
            1,
        )
    else:
        body += f"\n\n## Identity reconciliation\n\n{explanation}\n"
    now = datetime.now(timezone.utc).isoformat()
    body = item_store.append_change_log(
        body,
        now,
        "identity-repair",
        f"Rekeyed active duplicate {item_id} to {new_item_id}",
    )
    event_intent = events.build_planning_event(
        events.PLANNING_ITEM_UPDATED,
        {
            "ok": True,
            "id": new_item_id,
            "old-id": item_id,
            "item-id": new_item_id,
            "plan": plan,
            "path": str(target.relative_to(project_root)),
            "old_path": str(source.relative_to(project_root)),
            "updated_keys": ["id"],
            "created-by": active_fm.get("created-by", ""),
        },
        subject_kind="planning-item",
        subject_id=new_item_id,
    )
    durability.commit_mutation(
        project_root,
        {target: item_store.render_item(active_fm, body)},
        [source],
        operation="planning.item.rekey_duplicate",
        planning_event=event_intent,
    )
    if historical.read_bytes() != terminal_original:
        raise RuntimeError("historical Planning record changed during identity repair")
    result = {
        "ok": True,
        "id": new_item_id,
        "old_id": item_id,
        "state": active_fm["state"],
        "path": str(target.relative_to(project_root)),
    }
    events.publish_planning_event_intent(project_root, event_intent)
    return result
