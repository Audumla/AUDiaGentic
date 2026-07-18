"""Foundation workflow engine.

Generic, host-agnostic workflow infrastructure: state machines, lifecycle
actions, frontmatter assembly, relationships, and ID generation.
"""

from .actions import WorkflowActionExecutor, render
from .frontmatter import FrontmatterBuilder
from .id_gen import next_id
from .interfaces import ItemView, WorkflowConfig, WorkflowContext
from .state_machine import StateMachine
from .transition_engine import TransitionConfig, TransitionEngine
from .transitions import (
    in_state_set,
    is_known_state,
    load_workflow,
    states_in_set,
    transition_allowed,
)
from .util import Relationships, body_has_section, extract_ref_ids, now_iso, slugify

__all__ = [
    "FrontmatterBuilder",
    "ItemView",
    "Relationships",
    "StateMachine",
    "TransitionConfig",
    "TransitionEngine",
    "WorkflowActionExecutor",
    "WorkflowConfig",
    "WorkflowContext",
    "body_has_section",
    "extract_ref_ids",
    "in_state_set",
    "is_known_state",
    "load_workflow",
    "next_id",
    "now_iso",
    "render",
    "slugify",
    "states_in_set",
    "transition_allowed",
]
