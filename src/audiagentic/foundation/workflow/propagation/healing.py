"""Hierarchy state validation and self-healing utilities.

Kept separate from the engine because healing is opt-in and never runs on the
hot propagation path.
"""

from __future__ import annotations

import logging
from typing import Any

from ..util import extract_ref_ids
from .parents import find_parents

logger = logging.getLogger(__name__)


def validate(engine: Any, item_id: str) -> list[dict[str, Any]]:
    """Validate state consistency for ``item_id`` and its parents."""
    item_view = engine.ctx.lookup(item_id)
    if not item_view or not item_view.data:
        return [{"error": "Item not found", "item_id": item_id}]
    kind = getattr(item_view, "kind", None) or item_view.data.get("kind")
    if not kind:
        return [{"error": "Item has no kind", "item_id": item_id}]

    kind_config = engine.workflow_config.get("kinds", {}).get(kind, {})
    if not kind_config.get("enabled", True):
        return []

    parent_kind = kind_config.get("parent_kind")
    parent_field = kind_config.get("parent_field")
    if not parent_kind or not parent_field:
        return []

    errors: list[dict[str, Any]] = []
    cfg = engine.config
    for parent_id, found_parent_kind in find_parents(
        engine.ctx, item_id, parent_kind, parent_field
    ):
        parent_view = engine.ctx.lookup(parent_id)
        if not parent_view or not parent_view.data:
            errors.append(
                {
                    "error": "Parent not found",
                    "item_id": item_id,
                    "parent_id": parent_id,
                    "parent_kind": found_parent_kind,
                }
            )
            continue

        item_workflow = item_view.data.get("workflow")
        parent_workflow = parent_view.data.get("workflow")
        item_state = item_view.data.get("state", cfg.initial_state(kind, item_workflow))
        parent_state = parent_view.data.get(
            "state", cfg.initial_state(found_parent_kind, parent_workflow)
        )

        parent_complete = cfg.state_in_set(
            found_parent_kind, parent_state, "complete", parent_workflow
        )
        parent_initial = parent_state == cfg.initial_state(found_parent_kind, parent_workflow)
        item_active = cfg.state_in_set(kind, item_state, "active", item_workflow)
        item_complete = cfg.state_in_set(kind, item_state, "complete", item_workflow)

        if parent_complete:
            errors.extend(_check_children_complete(engine, parent_view, parent_field, parent_id))
        elif parent_initial and (item_active or item_complete):
            errors.append(
                {
                    "error": "Child is active but parent is in initial state",
                    "parent_id": parent_id,
                    "parent_state": parent_state,
                    "child_id": item_id,
                    "child_state": item_state,
                }
            )

    return errors


def heal(engine: Any, item_id: str, auto_fix: bool = False) -> dict[str, Any]:
    """Validate ``item_id`` and optionally apply safe state fixes."""
    result: dict[str, Any] = {"errors": [], "fixes": []}
    errors = validate(engine, item_id)
    result["errors"] = errors
    if not errors:
        return result

    healing_config = engine.workflow_config.get("healing", {})
    auto_fix = auto_fix or healing_config.get("auto_fix", False)
    log_only = healing_config.get("log_only", not auto_fix)

    for error in errors:
        fix = _suggest(engine, error)
        result["fixes"].append(fix)

        if auto_fix and not log_only and fix.get("can_auto_fix"):
            try:
                _apply(engine, fix)
                fix["applied"] = True
                logger.info(
                    "Applied healing fix: %s -> %s", fix.get("target_id"), fix.get("target_state")
                )
            except Exception as exc:
                logger.error("Failed to apply healing fix: %s", exc, exc_info=True)
                fix["applied"] = False
                fix["error"] = str(exc)
        else:
            logger.warning(
                "Healing fix not applied (auto_fix=%s, log_only=%s): %s", auto_fix, log_only, fix
            )

    return result


def _check_children_complete(
    engine: Any, parent_view: Any, parent_field: str, parent_id: str
) -> list[dict[str, Any]]:
    cfg = engine.config
    errors: list[dict[str, Any]] = []
    parent_state = parent_view.data.get("state")
    for ref_id in extract_ref_ids(parent_view.data.get(parent_field, [])):
        child_view = engine.ctx.lookup(ref_id)
        if not child_view or not child_view.data:
            continue
        child_kind = getattr(child_view, "kind", None) or child_view.data.get("kind")
        child_workflow = child_view.data.get("workflow")
        child_state = child_view.data.get(
            "state", cfg.initial_state(child_kind, child_workflow)
        )
        if cfg.state_in_set(child_kind, child_state, "complete", child_workflow):
            continue
        if cfg.state_in_set(child_kind, child_state, "terminal", child_workflow):
            continue
        errors.append(
            {
                "error": "Parent is complete but child is not complete",
                "parent_id": parent_id,
                "parent_state": parent_state,
                "child_id": ref_id,
                "child_state": child_state,
            }
        )
    return errors


def _suggest(engine: Any, error: dict[str, Any]) -> dict[str, Any]:
    cfg = engine.config
    error_type = error.get("error", "")

    if error_type == "Parent is complete but child is not complete":
        child_id = error.get("child_id")
        target = None
        if child_id:
            view = engine.ctx.lookup(child_id)
            if view and view.data:
                states = cfg.states_in_set(view.kind, "complete", view.data.get("workflow"))
                if states:
                    target = states[0]
        return {
            "error": error,
            "suggestion": "Mark child complete or change parent state",
            "target_id": child_id,
            "target_state": target,
            "can_auto_fix": False,
        }

    if error_type == "Child is active but parent is in initial state":
        parent_id = error.get("parent_id")
        target = None
        if parent_id:
            view = engine.ctx.lookup(parent_id)
            if view and view.data:
                target = _pick_parent_advance(cfg, view)
        return {
            "error": error,
            "suggestion": "Advance parent toward active state",
            "target_id": parent_id,
            "target_state": target,
            "can_auto_fix": bool(target),
        }

    return {"error": error, "suggestion": "Manual review required", "can_auto_fix": False}


def _pick_parent_advance(cfg: Any, parent_view: Any) -> str | None:
    workflow_name = parent_view.data.get("workflow")
    current = parent_view.data.get("state")
    workflow = cfg.workflow_for(parent_view.kind, workflow_name)
    next_states = workflow.get("transitions", {}).get(current, [])
    active = set(cfg.states_in_set(parent_view.kind, "active", workflow_name))
    blocked = set(cfg.states_in_set(parent_view.kind, "blocked", workflow_name))

    for candidate in next_states:
        if candidate in active and candidate not in blocked:
            return candidate
    for candidate in cfg.states_in_set(parent_view.kind, "initial", workflow_name):
        if candidate != current and candidate in next_states:
            return candidate
    if next_states:
        return next_states[0]
    for candidate in cfg.states_in_set(parent_view.kind, "initial", workflow_name):
        if candidate != current:
            return candidate
    for candidate in cfg.states_in_set(parent_view.kind, "active", workflow_name):
        if candidate != current:
            return candidate
    return None


def _apply(engine: Any, fix: dict[str, Any]) -> None:
    target_id = fix.get("target_id")
    target_state = fix.get("target_state")
    if not target_id or not target_state:
        raise ValueError("Fix must have target_id and target_state")
    engine.ctx.state(
        id_=target_id,
        new_state=target_state,
        metadata={"triggered_by": "healing", "healing_fix": True},
    )
