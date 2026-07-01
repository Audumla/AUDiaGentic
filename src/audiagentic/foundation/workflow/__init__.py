"""Foundation workflow engine.

Generic, host-agnostic workflow infrastructure: state machine, propagation
engine, lifecycle actions, frontmatter assembly, relationships, ID generation.
"""

from .actions import WorkflowActionExecutor, render
from .frontmatter import FrontmatterBuilder
from .id_gen import next_id
from .interfaces import ItemView, WorkflowConfig, WorkflowContext
from .propagation import StatePropagationEngine, WorkflowItemAPI
from .state_machine import StateMachine
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
    "StatePropagationEngine",
    "WorkflowActionExecutor",
    "WorkflowConfig",
    "WorkflowContext",
    "WorkflowItemAPI",
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
