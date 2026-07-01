"""Slim, host-agnostic state-transition primitives.

Components define their states and transitions in a YAML workflow file and use
these helpers to validate transitions. The shared logic here owns only the
transition-table semantics; each host keeps its own storage and error reporting.

Workflow file schema::

    kinds:
      <kind>:
        default-workflow: <name>          # optional; defaults to the sole workflow
        workflows:
          <name>:
            initial: <state>
            values: [<state>, ...]
            transitions:
              <state>: [<next-state>, ...]
            state-sets:                    # optional named sets (e.g. terminal)
              <set-name>: [<state>, ...]
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_workflow(path: str | Path, kind: str, name: str | None = None) -> dict[str, Any]:
    """Load a single workflow definition (values/transitions/state-sets/initial).

    Raises KeyError if the kind or named workflow is not present.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    spec = (data.get("kinds") or {}).get(kind)
    if spec is None:
        raise KeyError(f"workflow kind not defined: {kind}")
    workflows = spec.get("workflows") or {}
    wf_name = name or spec.get("default-workflow") or next(iter(workflows), None)
    workflow = workflows.get(wf_name) if wf_name else None
    if workflow is None:
        raise KeyError(f"workflow not defined: {kind}/{wf_name}")
    return workflow


def is_known_state(workflow: dict[str, Any], state: str) -> bool:
    """True if ``state`` is a declared value of the workflow."""
    return state in (workflow.get("values") or [])


def transition_allowed(workflow: dict[str, Any], old: str, new: str) -> bool:
    """True if moving ``old -> new`` is permitted by the workflow's transitions."""
    return new in (workflow.get("transitions") or {}).get(old, [])


def states_in_set(workflow: dict[str, Any], set_name: str) -> list[str]:
    """Return the states in a named state-set (empty if undefined)."""
    return list((workflow.get("state-sets") or {}).get(set_name, []))


def in_state_set(workflow: dict[str, Any], state: str | None, set_name: str) -> bool:
    """True if ``state`` belongs to the named state-set."""
    return state in (workflow.get("state-sets") or {}).get(set_name, [])
