"""AUDiaGentic knowledge component v0.7.0.

Deterministic knowledge state management with event-driven sync.
"""

__version__ = "0.7.0"


def setup_event_subscriptions() -> None:
    """Setup event bus subscriptions for knowledge component.

    This function must be called explicitly by the owner component (e.g., planning)
    to subscribe to planning state change events. This follows the component
    architecture standard where components do not subscribe at import time.

    Subscribes to:
        - planning.item.state.changed: Triggers knowledge sync actions

    Standard: standard-0011 (Component architecture standard, rule #28)
    """
    try:
        from audiagentic.interoperability import get_bus

        from .events import on_planning_state_change

        bus = get_bus()
        bus.subscribe("planning.item.state.changed", on_planning_state_change)
    except ImportError:
        pass
    except Exception:
        pass
