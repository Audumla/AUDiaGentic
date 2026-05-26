"""Unit tests for foundation/workflow/propagation/rules.py."""

from __future__ import annotations

import pytest

from audiagentic.foundation.workflow.propagation.rules import (
    action_complete_parent,
    rule_all_children_in_set,
    rule_none,
    rule_parent_in_set,
    rule_parent_not_in_set,
)

from .conftest import FakeContext

# ── engine stub ───────────────────────────────────────────────────────────────

class FakeEngine:
    """Minimal engine-shaped object rules can call into."""

    def __init__(self, ctx: FakeContext, workflow_config: dict | None = None) -> None:
        self.ctx = ctx
        self.config = ctx.config
        self.workflow_config = workflow_config or {}


# ── rule_none ─────────────────────────────────────────────────────────────────

def test_rule_none_always_false() -> None:
    engine = FakeEngine(FakeContext())
    assert rule_none(engine, "c-1", "p-1", "done") is False


def test_rule_none_with_when_still_false() -> None:
    engine = FakeEngine(FakeContext())
    assert rule_none(engine, "c-1", "p-1", "done", {"state_set": "complete"}) is False


# ── rule_parent_in_set ────────────────────────────────────────────────────────

def test_rule_parent_in_set_true_when_parent_in_set() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="draft")
    engine = FakeEngine(ctx)
    result = rule_parent_in_set(engine, "c-1", "p-1", "active", {"state_set": "initial"})
    assert result is True


def test_rule_parent_in_set_false_when_parent_not_in_set() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active")
    engine = FakeEngine(ctx)
    result = rule_parent_in_set(engine, "c-1", "p-1", "active", {"state_set": "initial"})
    assert result is False


def test_rule_parent_in_set_false_when_parent_not_found() -> None:
    ctx = FakeContext()
    engine = FakeEngine(ctx)
    result = rule_parent_in_set(engine, "c-1", "ghost", "active", {"state_set": "initial"})
    assert result is False


def test_rule_parent_in_set_false_when_no_when() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="draft")
    engine = FakeEngine(ctx)
    assert rule_parent_in_set(engine, "c-1", "p-1", "active", None) is False


def test_rule_parent_in_set_false_when_no_state_set() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="draft")
    engine = FakeEngine(ctx)
    assert rule_parent_in_set(engine, "c-1", "p-1", "active", {}) is False


# ── rule_parent_not_in_set ────────────────────────────────────────────────────

def test_rule_parent_not_in_set_true_when_parent_outside_set() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active")
    engine = FakeEngine(ctx)
    result = rule_parent_not_in_set(engine, "c-1", "p-1", "done", {"state_set": "initial"})
    assert result is True


def test_rule_parent_not_in_set_false_when_parent_inside_set() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="draft")
    engine = FakeEngine(ctx)
    result = rule_parent_not_in_set(engine, "c-1", "p-1", "done", {"state_set": "initial"})
    assert result is False


def test_rule_parent_not_in_set_false_when_parent_not_found() -> None:
    ctx = FakeContext()
    engine = FakeEngine(ctx)
    assert rule_parent_not_in_set(engine, "c-1", "ghost", "done", {"state_set": "initial"}) is False


# ── rule_all_children_in_set ─────────────────────────────────────────────────

def _all_children_engine(children: dict[str, str]) -> FakeEngine:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=list(children))
    for cid, state in children.items():
        ctx.add_item(cid, "task", state=state)
    wf_config = {
        "kinds": {
            "task": {
                "parent_kind": "plan",
                "parent_field": "task_refs",
            }
        }
    }
    return FakeEngine(ctx, workflow_config=wf_config)


def test_rule_all_children_in_set_true_when_all_in_set() -> None:
    engine = _all_children_engine({"t-1": "done", "t-2": "done"})
    result = rule_all_children_in_set(
        engine, "t-1", "p-1", "done", {"state_set": "complete"}
    )
    assert result is True


def test_rule_all_children_in_set_false_when_one_not_in_set() -> None:
    engine = _all_children_engine({"t-1": "done", "t-2": "active"})
    result = rule_all_children_in_set(
        engine, "t-1", "p-1", "done", {"state_set": "complete"}
    )
    assert result is False


def test_rule_all_children_in_set_false_when_no_children() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=[])
    ctx.add_item("t-1", "task", state="done")
    wf_config = {"kinds": {"task": {"parent_kind": "plan", "parent_field": "task_refs"}}}
    engine = FakeEngine(ctx, wf_config)
    assert rule_all_children_in_set(engine, "t-1", "p-1", "done", {"state_set": "complete"}) is False


def test_rule_all_children_in_set_ignores_missing_siblings() -> None:
    # Dangling refs are silently skipped — only resolvable siblings are checked.
    # With task_refs=["t-1", "ghost"] and only t-1 in items (done), rule passes.
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1", "ghost"])
    ctx.add_item("t-1", "task", state="done")
    wf_config = {"kinds": {"task": {"parent_kind": "plan", "parent_field": "task_refs"}}}
    engine = FakeEngine(ctx, wf_config)
    assert rule_all_children_in_set(engine, "t-1", "p-1", "done", {"state_set": "complete"}) is True


def test_rule_all_children_in_set_false_when_no_when() -> None:
    engine = _all_children_engine({"t-1": "done"})
    assert rule_all_children_in_set(engine, "t-1", "p-1", "done", None) is False


def test_rule_all_children_in_set_false_when_parent_not_found() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="done")
    wf_config = {"kinds": {"task": {"parent_kind": "plan", "parent_field": "task_refs"}}}
    engine = FakeEngine(ctx, wf_config)
    assert rule_all_children_in_set(engine, "t-1", "ghost", "done", {"state_set": "complete"}) is False


# ── action_complete_parent ────────────────────────────────────────────────────

def test_action_complete_parent_raises_without_blocking_set() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="done")
    engine = FakeEngine(ctx, {})
    with pytest.raises(ValueError, match="parent_blocking_set"):
        action_complete_parent(
            engine, "t-1",
            {"required_state_set": "complete", "parent_field": "plan_ref", "target_state": "done"},
            {},
        )


def test_action_complete_parent_returns_empty_when_source_not_in_required_set() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="active")
    engine = FakeEngine(ctx, {})
    result = action_complete_parent(
        engine, "t-1",
        {
            "required_state_set": "complete",
            "parent_field": "plan_ref",
            "target_state": "done",
            "parent_blocking_set": "terminal",
        },
        {},
    )
    assert result == []


def test_action_complete_parent_completes_parent_when_all_siblings_done() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1", "t-2"])
    ctx.add_item("t-1", "task", state="done", plan_ref="p-1")
    ctx.add_item("t-2", "task", state="done", plan_ref="p-1")
    engine = FakeEngine(ctx, {"kinds": {"task": {"parent_kind": "plan", "parent_field": "plan_ref"}}})
    result = action_complete_parent(
        engine, "t-1",
        {
            "required_state_set": "complete",
            "parent_field": "plan_ref",
            "target_state": "done",
            "parent_blocking_set": "terminal",
        },
        {},
    )
    assert ("p-1", "plan", "done") in result


def test_action_complete_parent_completes_reverse_linked_parent() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1", "t-2"])
    ctx.add_item("t-1", "task", state="done")
    ctx.add_item("t-2", "task", state="done")
    engine = FakeEngine(ctx, {"kinds": {"task": {"parent_kind": "plan", "parent_field": "task_refs"}}})
    result = action_complete_parent(
        engine, "t-1",
        {
            "required_state_set": "complete",
            "parent_field": "task_refs",
            "target_state": "done",
            "parent_blocking_set": "terminal",
        },
        {},
    )
    assert ("p-1", "plan", "done") in result


def test_action_complete_parent_skips_parent_in_blocking_set() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="cancelled", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="done", plan_ref="p-1")
    engine = FakeEngine(ctx, {})
    result = action_complete_parent(
        engine, "t-1",
        {
            "required_state_set": "complete",
            "parent_field": "plan_ref",
            "target_state": "done",
            "parent_blocking_set": "terminal",
        },
        {},
    )
    assert result == []


def test_action_complete_parent_returns_empty_when_one_sibling_incomplete() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1", "t-2"])
    ctx.add_item("t-1", "task", state="done", plan_ref="p-1")
    ctx.add_item("t-2", "task", state="active", plan_ref="p-1")
    engine = FakeEngine(ctx, {})
    result = action_complete_parent(
        engine, "t-1",
        {
            "required_state_set": "complete",
            "parent_field": "plan_ref",
            "target_state": "done",
            "parent_blocking_set": "terminal",
        },
        {},
    )
    assert result == []
