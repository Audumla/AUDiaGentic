"""AUDiaGentic knowledge component v0.7.0.

Deterministic knowledge state management with event-driven sync.
"""

__version__ = "0.7.0"

# Tracks the active knowledge subscription handle. Ensures setup_event_subscriptions()
# is idempotent — multiple PlanningAPI instances (e.g. in tm_helper) don't stack up
# duplicate handlers on the singleton EventBus.
_knowledge_subscription_handle = None


def setup_event_subscriptions() -> None:
    """Setup event bus subscriptions for knowledge component.

    This function must be called explicitly by the owner component (e.g., planning)
    to subscribe to planning state change events. This follows the component
    architecture standard where components do not subscribe at import time.

    Idempotent: subsequent calls are no-ops if already subscribed.

    Subscribes to:
        - planning.item.state.changed: Triggers knowledge sync actions

    Standard: standard-0011 (Component architecture standard, rule #28)
    """
    global _knowledge_subscription_handle
    if _knowledge_subscription_handle is not None:
        return
    try:
        from audiagentic.interoperability import get_bus

        from .events import on_planning_state_change

        bus = get_bus()
        _knowledge_subscription_handle = bus.subscribe(
            "planning.item.state.changed", on_planning_state_change
        )
    except ImportError:
        pass
    except Exception:
        pass
