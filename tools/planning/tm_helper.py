#!/usr/bin/env python3
"""Thin wrapper around PlanningAPI for agent-friendly access.

Usage:
    from tools.tm_helper import tm

    tm.new_task("Label", "Summary", spec="spec-0001", domain="core")
    tm.state("task-0001", "ready")
    tasks = tm.next_tasks(domain="core")
"""

from __future__ import annotations
import sys
from pathlib import Path
from typing import Any

# Auto-detect project root
_ROOT = None
for p in [Path.cwd(), *Path.cwd().parents]:
    if (p / ".audiagentic" / "planning").exists():
        _ROOT = p
        break
if _ROOT is None:
    _ROOT = Path(__file__).resolve().parents[1]

# Setup path and import
for _p in (str(_ROOT), str(_ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from audiagentic.planning.app.api import PlanningAPI

_api = PlanningAPI(_ROOT)


def new_request(label: str, summary: str) -> dict[str, Any]:
    """Create a new request."""
    item = _api.new("request", label=label, summary=summary)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def new_spec(
    label: str, summary: str, request_refs: list[str] | None = None
) -> dict[str, Any]:
    """Create a new specification."""
    item = _api.new("spec", label=label, summary=summary, request_refs=request_refs)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def new_plan(label: str, summary: str, spec: str | None = None) -> dict[str, Any]:
    """Create a new plan."""
    item = _api.new("plan", label=label, summary=summary, spec=spec)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def new_task(
    label: str,
    summary: str,
    spec: str,
    domain: str = "core",
    target: str | None = None,
    parent: str | None = None,
) -> dict[str, Any]:
    """Create a new task."""
    item = _api.new(
        "task",
        label=label,
        summary=summary,
        spec=spec,
        domain=domain,
        target=target,
        parent=parent,
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def new_wp(label: str, summary: str, plan: str, domain: str = "core") -> dict[str, Any]:
    """Create a new work package."""
    item = _api.new("wp", label=label, summary=summary, plan=plan, domain=domain)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def new_standard(label: str, summary: str) -> dict[str, Any]:
    """Create a new standard."""
    item = _api.new("standard", label=label, summary=summary)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def state(id_: str, new_state: str) -> dict[str, Any]:
    """Change state of an object."""
    item = _api.state(id_, new_state)
    return {"id": item.data["id"], "state": item.data["state"]}


def move(id_: str, domain: str) -> dict[str, Any]:
    """Move task/wp to a different domain."""
    item = _api.move(id_, domain)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def update(
    id_: str,
    label: str | None = None,
    summary: str | None = None,
    append: str | None = None,
) -> dict[str, Any]:
    """Update an object."""
    item = _api.update(id_, label=label, summary=summary, body_append=append)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def get_content(id_: str) -> str:
    """Get markdown content without YAML frontmatter."""
    return _api.get_content(id_)


def update_content(
    id_: str,
    content: str,
    mode: str = "replace",
    section: str | None = None,
    position: int | None = None,
) -> dict[str, Any]:
    """Update file content with various modes.

    Args:
        id_: Object ID to update
        content: Markdown content to write
        mode: 'replace', 'append', 'insert', or 'section'
        section: Section header to update (for mode='section')
        position: Line position to insert (for mode='insert')
    """
    item = _api.update_content(id_, content, mode, section, position)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def create_with_content(
    kind: str,
    label: str,
    summary: str,
    content: str,
    domain: str = "core",
    spec: str | None = None,
    plan: str | None = None,
    parent: str | None = None,
    target: str | None = None,
    workflow: str | None = None,
    request_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Create planning object with full content.

    Args:
        kind: Object type (plan/request/spec/task/wp/standard)
        label: Object label
        summary: Object summary
        content: Full markdown content (without YAML frontmatter)
        domain: Domain for task/wp
        spec: Spec reference for plan/task
        plan: Plan reference for wp
        parent: Parent task reference
        target: Target reference
        workflow: Workflow name
        request_refs: Request references for spec
    """
    item = _api.create_with_content(
        kind,
        label,
        summary,
        content,
        domain,
        spec,
        plan,
        parent,
        target,
        workflow,
        request_refs,
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def relink(
    src: str, field: str, dst: str, seq: int | None = None, display: str | None = None
) -> dict[str, Any]:
    """Create a relationship between objects."""
    item = _api.relink(src, field, dst, seq, display)
    return {"id": item.data["id"], "field": field}


def package(
    plan: str, tasks: list[str], label: str, summary: str, domain: str = "core"
) -> dict[str, Any]:
    """Create a work package from tasks."""
    item = _api.package(plan, tasks, label, summary, domain)
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}


def validate() -> list[str]:
    """Validate all planning objects. Returns list of errors."""
    return _api.validate()


def index() -> None:
    """Rebuild indexes."""
    _api.index()


def reconcile() -> dict[str, Any]:
    """Reconcile planning objects."""
    return _api.reconcile()


def show(id_: str) -> dict[str, Any]:
    """Show object details."""
    return _api.extracts.show(id_)


def extract(
    id_: str, with_related: bool = False, with_resources: bool = False
) -> dict[str, Any]:
    """Extract object with optional context."""
    return _api.extracts.extract(id_, with_related, with_resources)


def list_kind(kind: str | None = None) -> list[dict[str, Any]]:
    """List objects, optionally filtered by kind."""
    items = _api._scan()
    if kind:
        items = [i for i in items if i.kind == kind]
    return [
        {
            "id": i.data["id"],
            "kind": i.kind,
            "label": i.data["label"],
            "state": i.data["state"],
        }
        for i in items
    ]


def next_items(
    kind: str = "task", state: str = "ready", domain: str | None = None
) -> list[dict[str, Any]]:
    """Get next available items."""
    return _api.next_items(kind, state, domain)


def next_tasks(state: str = "ready", domain: str | None = None) -> list[dict[str, Any]]:
    """Get next available tasks."""
    return next_items("task", state, domain)


def claim(kind: str, id_: str, holder: str, ttl: int | None = None) -> dict[str, Any]:
    """Claim an object."""
    return _api.claim(kind, id_, holder, ttl)


def unclaim(id_: str) -> bool:
    """Release a claim."""
    return _api.unclaim(id_)


def claims(kind: str | None = None) -> list[dict[str, Any]]:
    """List claims."""
    return _api.claims(kind)


def standards(id_: str) -> list[str]:
    """Get effective standards for an object."""
    return _api.standards(id_)


def events(tail: int = 20) -> list[dict[str, Any]]:
    """Get recent events."""
    import json

    p = _ROOT / ".audiagentic/planning/events/events.jsonl"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").strip().splitlines()[-tail:]
    return [json.loads(x) for x in lines if x.strip()]


def status() -> dict[str, Any]:
    """Get status summary by kind/state."""
    items = _api._scan()
    out = {}
    for i in items:
        out.setdefault(i.kind, {})
        out[i.kind].setdefault(i.data["state"], 0)
        out[i.kind][i.data["state"]] += 1
    return out
