"""Config-driven propagation rule implementations.

These functions are referenced by name in the state_propagation.yaml config.
They operate purely on semantic state sets defined in configuration, with no
hardcoded state names or legacy fallbacks.
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
    """Trigger parent when parent state is in configured semantic set.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child
        when: Rule condition config containing 'state_set'

    Returns:
        True if parent is in configured state set
    """
    parent_view = engine._planning_api.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False

    parent_kind = getattr(parent_view, "kind", None) or parent_view.data.get("kind")
    parent_state = parent_view.data.get("state")
    state_set = (when or {}).get("state_set")

    if not state_set or not engine.config or not parent_kind:
        return False

    return engine.config.state_in_set(
        parent_kind, parent_state, state_set, parent_view.data.get("workflow")
    )


def rule_all_children_in_set(
    engine: Any, child_id: str, parent_id: str, new_state: str, when: dict[str, Any] | None = None
) -> bool:
    """Check if all sibling children are in configured semantic state set.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child
        when: Rule condition config containing 'state_set'

    Returns:
        True if all siblings are in configured set
    """
    parent_view = engine._planning_api.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False

    child_view = engine._planning_api.lookup(child_id)
    if not child_view or not child_view.data:
        return False

    child_kind = getattr(child_view, "kind", None) or child_view.data.get("kind")
    child_config = engine._config.get("kinds", {}).get(child_kind, {})
    parent_kind = child_config.get("parent_kind")
    parent_field = child_config.get("parent_field")

    if not parent_kind or not parent_field:
        return False

    state_set = (when or {}).get("state_set")
    if not state_set:
        return False

    child_ids = engine._linked_child_ids(parent_id, parent_kind, child_kind, parent_field)
    if not child_ids:
        return False

    for cid in child_ids:
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
    """Trigger parent when parent state is not in configured semantic set.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child
        when: Rule condition config containing 'state_set'

    Returns:
        True if parent is not in configured state set
    """
    parent_view = engine._planning_api.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False

    parent_kind = getattr(parent_view, "kind", None) or parent_view.data.get("kind")
    parent_state = parent_view.data.get("state")
    state_set = (when or {}).get("state_set")

    if not state_set or not engine.config or not parent_kind:
        return False

    return not engine.config.state_in_set(
        parent_kind, parent_state, state_set, parent_view.data.get("workflow")
    )


def action_complete_parent(
    engine: Any,
    item_id: str,
    action_config: dict[str, Any],
    state_rules: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Complete parent items when all sibling children are in configured semantic set.

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
    parent_blocking_set = action_config.get("parent_blocking_set")

    if not required_state_set or not parent_field or not target_state:
        return []
    if not parent_blocking_set:
        raise ValueError("action_complete_parent requires parent_blocking_set")

    if not engine.config.state_in_set(
        source_kind, source_view.data.get("state"), required_state_set, source_view.data.get("workflow")
    ):
        return []

    parent_refs = engine._extract_ref_ids(source_view.data.get(parent_field, []))

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
        sibling_ids = engine._linked_child_ids(parent_id, parent_kind, source_kind, parent_field)
        if not sibling_ids:
            continue
        for sibling_id in sibling_ids:
            sibling_view = engine._planning_api.lookup(sibling_id)
            if not sibling_view or not sibling_view.data:
                siblings_complete = False
                break
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
