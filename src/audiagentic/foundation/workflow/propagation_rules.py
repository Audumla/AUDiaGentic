"""Backward-compatible re-export of propagation rule implementations.

The canonical home is :mod:`audiagentic.foundation.workflow.propagation.rules`.
Existing config files reference this dotted path; keep the shim until callers
are migrated.
"""

from .propagation.rules import (
    action_complete_parent,
    rule_all_children_in_set,
    rule_none,
    rule_parent_in_set,
    rule_parent_not_in_set,
)

__all__ = [
    "action_complete_parent",
    "rule_all_children_in_set",
    "rule_none",
    "rule_parent_in_set",
    "rule_parent_not_in_set",
]
