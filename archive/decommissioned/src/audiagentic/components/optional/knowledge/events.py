"""Event processing and handling for knowledge component.

This module re-exports the public API from split sub-modules for backward compatibility.
- event_state: state I/O, fingerprinting, validation
- event_scanner: scanning and proposal generation
- event_handlers: pipeline and action dispatch
"""

from .event_handlers import (
    action_generate_sync_proposal,
    action_ignore,
    action_mark_stale,
    action_mark_stale_and_generate_sync_proposal,
    load_event_handlers,
    on_planning_state_change,
    process_events,
)
from .event_scanner import (
    record_event_baseline,
    scan_events,
)
from .event_state import (
    load_event_adapters,
    load_event_state,
    prune_event_state,
    save_event_state,
)

__all__ = [
    "load_event_adapters",
    "load_event_state",
    "save_event_state",
    "prune_event_state",
    "record_event_baseline",
    "scan_events",
    "load_event_handlers",
    "process_events",
    "on_planning_state_change",
    "action_generate_sync_proposal",
    "action_mark_stale",
    "action_mark_stale_and_generate_sync_proposal",
    "action_ignore",
]
