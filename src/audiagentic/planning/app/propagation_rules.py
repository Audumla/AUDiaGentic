"""Config-driven propagation rule implementations.

These functions are referenced by name in the state_propagation.yaml config.
They can be replaced or extended without modifying the propagation engine.
"""

from typing import Any


def rule_none(engine: Any, child_id: str, parent_id: str, new_state: str) -> bool:
    """No propagation.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child

    Returns:
        False (no propagation)
    """
    return False


def rule_parent_in_set(
    engine: Any, child_id: str, parent_id: str, new_state: str, when: dict[str, Any] | None = None
) -> bool:
    """Trigger parent when parent state is in configured set.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child

    Returns:
        True if parent is in configured set
    """
    parent_view = engine._planning_api.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False

    parent_kind = getattr(parent_view, "kind", None) or parent_view.data.get("kind")
    initial_state = engine.config.initial_state(parent_kind) if engine.config and parent_kind else "ready"
    parent_state = parent_view.data.get("state", initial_state)
    state_set = (when or {}).get("state_set")
    if engine.config and parent_kind and state_set:
        return engine.config.state_in_set(
            parent_kind, parent_state, state_set, parent_view.data.get("workflow")
        )
    return parent_state == initial_state


def rule_all_children_in_set(
    engine: Any, child_id: str, parent_id: str, new_state: str, when: dict[str, Any] | None = None
) -> bool:
    """Check if all sibling children are in configured state set.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child

    Returns:
        True if all siblings are in configured set
    """
    parent_view = engine._planning_api.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False

    child_view = engine._planning_api.lookup(child_id)
    if not child_view or not child_view.data:
        return False

    # Get child kind from Item.kind attribute
    child_kind = getattr(child_view, "kind", None) or child_view.data.get("kind")
    child_config = engine._config.get("kinds", {}).get(child_kind, {})

    # Use the child's parent_field to find the field in parent that contains children
    child_field = child_config.get("parent_field")

    if not child_field:
        return False

    # Get all children from parent
    child_refs = parent_view.data.get(child_field, [])
    if isinstance(child_refs, str):
        child_refs = [child_refs]

    if not child_refs:
        return False

    state_set = (when or {}).get("state_set")
    if not state_set:
        return False

    # Check all children are in target set
    for ref in child_refs:
        # Handle both direct IDs and dict refs with 'ref' key
        cid = ref.get("ref") if isinstance(ref, dict) else ref

        sibling_view = engine._planning_api.lookup(cid)
        if not sibling_view or not sibling_view.data:
            return False

        sibling_kind = getattr(sibling_view, "kind", None) or sibling_view.data.get("kind")
        if not engine.config or not sibling_kind:
            return False
        if not engine.config.state_in_set(
            sibling_kind, sibling_view.data.get("state"), state_set, sibling_view.data.get("workflow")
        ):
            return False

    return True


def rule_parent_not_in_set(
    engine: Any, child_id: str, parent_id: str, new_state: str, when: dict[str, Any] | None = None
) -> bool:
    """Trigger parent when parent state is not in configured set.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child

    Returns:
        True if parent is not in configured set
    """
    parent_view = engine._planning_api.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False

    parent_kind = getattr(parent_view, "kind", None) or parent_view.data.get("kind")
    initial_state = engine.config.initial_state(parent_kind) if engine.config and parent_kind else "ready"
    parent_state = parent_view.data.get("state", initial_state)
    state_set = (when or {}).get("state_set")
    if engine.config and parent_kind and state_set:
        return not engine.config.state_in_set(
            parent_kind, parent_state, state_set, parent_view.data.get("workflow")
        )
    terminal_states = engine._config.get("terminal_states", [])
    return parent_state not in terminal_states


def action_complete_parent(
    engine: Any,
    item_id: str,
    action_config: dict[str, Any],
    state_rules: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Complete parent items when all sibling children are in configured set.

    Args:
        engine: StatePropagationEngine instance
        item_id: Source item ID that changed state
        action_config: Action config dict
        state_rules: State rules config for context

    Returns:
        List of (parent_id, parent_kind, target_state) tuples for propagation
    """
    source_view = engine._planning_api.lookup(item_id)
    if not source_view or not source_view.data:
        return []

    source_kind = getattr(source_view, "kind", None) or source_view.data.get("kind")
    if not source_kind or not engine.config:
        return []

    required_state_set = action_config.get("required_state_set")
    parent_field = action_config.get("parent_field")
    target_state = action_config.get("target_state")
    parent_blocking_set = action_config.get("parent_blocking_set", "terminal")
    if not required_state_set or not parent_field or not target_state:
        return []

    if not engine.config.state_in_set(
        source_kind, source_view.data.get("state"), required_state_set, source_view.data.get("workflow")
    ):
        return []

    parent_refs = source_view.data.get(parent_field, [])
    if isinstance(parent_refs, str):
        parent_refs = [parent_refs]

    propagations = []

    for parent_id in parent_refs:
        parent_view = engine._planning_api.lookup(parent_id)
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

        siblings_complete = True
        for sibling_view in engine._planning_api._scan():
            sibling_kind = getattr(sibling_view, "kind", None) or sibling_view.data.get("kind")
            if sibling_kind != source_kind:
                continue
            sibling_refs = sibling_view.data.get(parent_field, [])
            if isinstance(sibling_refs, str):
                sibling_refs = [sibling_refs]
            if parent_id not in sibling_refs:
                continue
            if not engine.config.state_in_set(
                source_kind,
                sibling_view.data.get("state"),
                required_state_set,
                sibling_view.data.get("workflow"),
            ):
                siblings_complete = False
                break

        if siblings_complete:
            propagations.append((parent_id, parent_kind, target_state))

    return propagations
