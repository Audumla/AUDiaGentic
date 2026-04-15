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


def rule_trigger_parent_if_ready(
    engine: Any, child_id: str, parent_id: str, new_state: str
) -> bool:
    """Trigger parent to enter new_state if parent is in 'ready' state.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child

    Returns:
        True if parent is in 'ready' state
    """
    parent_view = engine._planning_api.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False

    parent_state = parent_view.data.get("state", "ready")
    return parent_state == "ready"


def rule_check_all_children_done(
    engine: Any, child_id: str, parent_id: str, new_state: str
) -> bool:
    """Check if all sibling children are in new_state.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child

    Returns:
        True if all siblings are in new_state
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

    # Check all children are in target state
    for ref in child_refs:
        # Handle both direct IDs and dict refs with 'ref' key
        cid = ref.get("ref") if isinstance(ref, dict) else ref

        sibling_view = engine._planning_api.lookup(cid)
        if not sibling_view or not sibling_view.data:
            return False

        if sibling_view.data.get("state") != new_state:
            return False

    return True


def rule_trigger_parent_unless_terminal(
    engine: Any, child_id: str, parent_id: str, new_state: str
) -> bool:
    """Trigger parent to new_state unless parent is in terminal state.

    Args:
        engine: StatePropagationEngine instance
        child_id: Child item ID
        parent_id: Parent item ID
        new_state: New state of child

    Returns:
        True if parent is not in terminal state
    """
    parent_view = engine._planning_api.lookup(parent_id)
    if not parent_view or not parent_view.data:
        return False

    parent_state = parent_view.data.get("state", "ready")
    terminal_states = engine._config.get("terminal_states", ["done", "archived"])
    return parent_state not in terminal_states


def action_check_request_completion(
    engine: Any, item_id: str, state_rules: dict[str, Any]
) -> list[tuple[str, str, str]]:
    """Check if a request should auto-complete based on spec states.

    This action is called when a spec enters 'done' state. It checks if the
    request(s) this spec belongs to should be marked as done.

    Args:
        engine: StatePropagationEngine instance
        item_id: Spec ID that just changed state
        state_rules: State rules config for context

    Returns:
        List of (request_id, "request", "done") tuples for propagation
    """
    spec_view = engine._planning_api.lookup(item_id)
    if not spec_view or not spec_view.data:
        return []

    if spec_view.data.get("state") != "done":
        return []

    # Get the parent_field from spec config to find request references
    spec_kind = getattr(spec_view, "kind", None) or spec_view.data.get("kind")
    spec_config = engine._config.get("kinds", {}).get(spec_kind, {})
    parent_field = spec_config.get("parent_field")

    if not parent_field:
        return []

    # Find request(s) this spec belongs to
    request_refs = spec_view.data.get(parent_field, [])
    if isinstance(request_refs, str):
        request_refs = [request_refs]

    propagations = []

    for request_id in request_refs:
        request_view = engine._planning_api.lookup(request_id)
        if not request_view or not request_view.data:
            continue

        # Check if all specs for this request are done
        request_state = request_view.data.get("state", "ready")
        terminal_states = engine._config.get("terminal_states", ["done", "archived"])

        if request_state not in terminal_states:
            propagations.append((request_id, "request", "done"))

    return propagations
