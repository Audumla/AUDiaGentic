"""Compatibility imports for the relocated Agents Work event observer."""
from audiagentic.components.agents.work.event_observer import (  # noqa: F401
    GW_OUTCOME_TOPICS,
    GW_TOPIC_CANCEL_REQUESTED,
    GW_TOPIC_REQUESTED,
    EventObserver,
    get_event_observer,
)

__all__ = [
    "EventObserver", "get_event_observer", "GW_TOPIC_REQUESTED",
    "GW_TOPIC_CANCEL_REQUESTED", "GW_OUTCOME_TOPICS",
]
