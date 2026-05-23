"""Foundation workflow engine.

Generic, host-agnostic workflow infrastructure: state machine, propagation
engine, lifecycle actions, frontmatter assembly, relationships, ID generation.
"""

from .actions import WorkflowActionExecutor, render
from .frontmatter import FrontmatterBuilder
from .id_gen import next_id
from .interfaces import WorkflowConfig, WorkflowContext
from .item import ItemView
from .propagation import StatePropagationEngine, WorkflowItemAPI
from .rel import Relationships
from .state_machine import StateMachine
from .util import body_has_section, extract_ref_ids, now_iso, slugify

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
    "next_id",
    "now_iso",
    "render",
    "slugify",
]
