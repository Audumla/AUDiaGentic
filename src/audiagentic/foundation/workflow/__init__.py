"""Foundation workflow engine.

Generic workflow infrastructure for state machines, propagation, and actions.
Used by planning and other workflow-driven components.
"""

from .actions import WorkflowActionExecutor, render
from .frontmatter import FrontmatterBuilder
from .id_gen import next_id
from .interfaces import WorkflowConfig, WorkflowContext
from .item import ItemView
from .propagation import StatePropagationEngine
from .propagation_api import WorkflowItemAPI
from .rel import Relationships
from .state_machine import StateMachine
from .util import body_has_section, now_iso, slugify

__all__ = [
    "WorkflowConfig",
    "WorkflowContext",
    "WorkflowItemAPI",
    "ItemView",
    "StatePropagationEngine",
    "StateMachine",
    "WorkflowActionExecutor",
    "FrontmatterBuilder",
    "Relationships",
    "next_id",
    "render",
    "slugify",
    "now_iso",
    "body_has_section",
]
