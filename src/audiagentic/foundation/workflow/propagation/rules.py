"""Configurable propagation rule and action implementations.

Each function is referenced by dotted path in the propagation YAML config.
Signatures take the engine as first argument so rules can access the host
context and propagation config; rules themselves are otherwise generic.
"""

from __future__ import annotations

from typing import Any

from ..util import extract_ref_ids
from .parents import linked_child_ids


def rule_none(
    engine: Any,
    child_id: str,
    parent_id: str,
    new_state: str,
    when: dict[str, Any] | None = None,
) -> bool:
    return False


def rule_parent_in_set(
    engine: Any,
    child_id: str,
    parent_id: str,
    new_state: str,
    when: dict[str, Any] | None = None,
) -> bool:
    return _parent_in_set(engine, parent_id, when)


def rule_parent_not_in_set(
    engine: Any,
    child_id: str,
    parent_id: str,
    new_state: str,
    when: dict[str, Any] | None = None,
) -> bool:
    parent_view = engine.ctx.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False
    state_set = (when or {}).get("state_set")
    if not state_set or not engine.config:
        return False
    parent_kind = getattr(parent_view, "kind", None) or parent_view.data.get("kind")
    if not parent_kind:
        return False
    return not engine.config.state_in_set(
        parent_kind, parent_view.data.get("state"), state_set, parent_view.data.get("workflow")
    )


def rule_all_children_in_set(
    engine: Any,
    child_id: str,
    parent_id: str,
    new_state: str,
    when: dict[str, Any] | None = None,
) -> bool:
    parent_view = engine.ctx.lookup(parent_id)
    child_view = engine.ctx.lookup(child_id)
    if not parent_view or not parent_view.data or not child_view or not child_view.data:
        return False

    child_kind = getattr(child_view, "kind", None) or child_view.data.get("kind")
    kind_config = engine.workflow_config.get("kinds", {}).get(child_kind, {})
    parent_kind = kind_config.get("parent_kind")
    parent_field = kind_config.get("parent_field")
    state_set = (when or {}).get("state_set")
    if not parent_kind or not parent_field or not state_set or not engine.config:
        return False

    ids = linked_child_ids(engine.ctx, parent_id, parent_kind, child_kind, parent_field)
    if not ids:
        return False

    for cid in ids:
        sibling = engine.ctx.lookup(cid)
        if not sibling or not sibling.data:
            return False
        sibling_kind = getattr(sibling, "kind", None) or sibling.data.get("kind")
        if not sibling_kind:
            return False
        if not engine.config.state_in_set(
            sibling_kind, sibling.data.get("state"), state_set, sibling.data.get("workflow")
        ):
            return False
    return True


def action_complete_parent(
    engine: Any,
    item_id: str,
    action_config: dict[str, Any],
    state_rules: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Complete parent items when all sibling children are in the required state set."""
    source = engine.ctx.lookup(item_id)
    if not source or not source.data or not engine.config:
        return []

    source_kind = getattr(source, "kind", None) or source.data.get("kind")
    required_set = action_config.get("required_state_set")
    parent_field = action_config.get("parent_field")
    target_state = action_config.get("target_state")
    parent_blocking_set = action_config.get("parent_blocking_set")

    if not source_kind or not required_set or not parent_field or not target_state:
        return []
    if not parent_blocking_set:
        raise ValueError("action_complete_parent requires parent_blocking_set")

    if not engine.config.state_in_set(
        source_kind, source.data.get("state"), required_set, source.data.get("workflow")
    ):
        return []

    propagations: list[tuple[str, str, str]] = []
    for parent_id in extract_ref_ids(source.data.get(parent_field, [])):
        parent_view = engine.ctx.lookup(parent_id)
        if not parent_view or not parent_view.data:
            continue
        parent_kind = getattr(parent_view, "kind", None) or parent_view.data.get("kind")
        if not parent_kind:
            continue
        if engine.config.state_in_set(
            parent_kind,
            parent_view.data.get("state"),
            parent_blocking_set,
            parent_view.data.get("workflow"),
        ):
            continue

        sibling_ids = linked_child_ids(
            engine.ctx, parent_id, parent_kind, source_kind, parent_field
        )
        if not sibling_ids:
            continue
        if all(_sibling_in_set(engine, sid, source_kind, required_set) for sid in sibling_ids):
            propagations.append((parent_id, parent_kind, target_state))

    return propagations


def _parent_in_set(engine: Any, parent_id: str, when: dict[str, Any] | None) -> bool:
    parent_view = engine.ctx.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False
    state_set = (when or {}).get("state_set")
    if not state_set or not engine.config:
        return False
    parent_kind = getattr(parent_view, "kind", None) or parent_view.data.get("kind")
    if not parent_kind:
        return False
    return engine.config.state_in_set(
        parent_kind, parent_view.data.get("state"), state_set, parent_view.data.get("workflow")
    )


def _sibling_in_set(engine: Any, sibling_id: str, kind: str, state_set: str) -> bool:
    view = engine.ctx.lookup(sibling_id)
    if not view or not view.data:
        return False
    return engine.config.state_in_set(
        kind, view.data.get("state"), state_set, view.data.get("workflow")
    )
