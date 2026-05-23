"""Unit tests for foundation/workflow/state_machine.py.

All tests use FakeContext — no PlanningAPI, no filesystem, no event bus.
"""

from __future__ import annotations

import pytest

from audiagentic.foundation.workflow import StateMachine

from .conftest import FakeConfig, FakeContext

# ── helpers ───────────────────────────────────────────────────────────────────

def _make_ctx(**extra_config_kwargs) -> FakeContext:
    return FakeContext(config=FakeConfig())


# ── valid transitions ─────────────────────────────────────────────────────────

def test_valid_transition_updates_state() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    sm.state("t-1", "active")
    assert ctx.items["t-1"].data["state"] == "active"


def test_valid_transition_saves_item() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    sm.state("t-1", "active")
    assert any(id_ == "t-1" for id_, _ in ctx.saved)


def test_valid_transition_publishes_state_changed_event() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    sm.state("t-1", "active")
    ev = ctx.last_event("planning.item.state.changed")
    assert ev is not None
    assert ev["payload"]["old_state"] == "draft"
    assert ev["payload"]["new_state"] == "active"


def test_valid_transition_increments_index() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    sm.state("t-1", "active")
    assert ctx.indexed == 1


def test_valid_transition_returns_updated_item() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    result = sm.state("t-1", "active")
    assert result.data["state"] == "active"


# ── invalid transitions ───────────────────────────────────────────────────────

def test_unknown_target_state_raises() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    with pytest.raises(ValueError, match="unknown state"):
        sm.state("t-1", "nonexistent")


def test_disallowed_transition_raises() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    with pytest.raises(ValueError, match="invalid transition"):
        sm.state("t-1", "done")


def test_failed_transition_does_not_save() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    try:
        sm.state("t-1", "done")
    except ValueError:
        pass
    assert ctx.saved == []


def test_failed_transition_does_not_publish_event() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    try:
        sm.state("t-1", "done")
    except ValueError:
        pass
    assert ctx.events == []


# ── missing state field fallback ──────────────────────────────────────────────

def test_missing_state_field_falls_back_to_initial_state() -> None:
    """item.data without 'state' key must not raise KeyError."""
    ctx = _make_ctx()
    item = ctx.add_item("t-1", "task", state="draft")
    del item.data["state"]
    sm = StateMachine(ctx)
    sm.state("t-1", "active")
    assert ctx.items["t-1"].data["state"] == "active"


# ── lifecycle metadata tokens ─────────────────────────────────────────────────

def _ctx_with_action(transition: tuple[str, str], metadata_rules: dict) -> FakeContext:
    cfg = FakeConfig()
    cfg._lifecycle_transitions[("task",) + transition] = (
        "test_action",
        {"metadata": metadata_rules},
    )
    return FakeContext(config=cfg)


def test_metadata_token_now_sets_timestamp() -> None:
    ctx = _ctx_with_action(("draft", "active"), {"completed_at": "now"})
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active", actor="alice")
    assert ctx.items["t-1"].data["completed_at"] is not None
    assert "T" in ctx.items["t-1"].data["completed_at"]


def test_metadata_token_actor() -> None:
    ctx = _ctx_with_action(("draft", "active"), {"changed_by": "actor"})
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active", actor="alice")
    assert ctx.items["t-1"].data["changed_by"] == "alice"


def test_metadata_token_actor_or_system_uses_system_when_none() -> None:
    ctx = _ctx_with_action(("draft", "active"), {"changed_by": "actor_or_system"})
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active", actor=None)
    assert ctx.items["t-1"].data["changed_by"] == "system"


def test_metadata_token_actor_or_system_prefers_actor() -> None:
    ctx = _ctx_with_action(("draft", "active"), {"changed_by": "actor_or_system"})
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active", actor="bob")
    assert ctx.items["t-1"].data["changed_by"] == "bob"


def test_metadata_token_reason() -> None:
    ctx = _ctx_with_action(("draft", "active"), {"why": "reason"})
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active", reason="testing")
    assert ctx.items["t-1"].data["why"] == "testing"


def test_metadata_token_reason_or_empty() -> None:
    ctx = _ctx_with_action(("draft", "active"), {"why": "reason_or_empty"})
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active", reason=None)
    assert ctx.items["t-1"].data["why"] == ""


def test_metadata_token_null_sets_none() -> None:
    ctx = _ctx_with_action(("draft", "active"), {"cleared": "null"})
    ctx.add_item("t-1", "task", state="draft", cleared="old-value")
    StateMachine(ctx).state("t-1", "active")
    assert ctx.items["t-1"].data["cleared"] is None


def test_metadata_literal_string_passthrough() -> None:
    ctx = _ctx_with_action(("draft", "active"), {"source": "automated"})
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active")
    assert ctx.items["t-1"].data["source"] == "automated"


def test_metadata_token_included_in_event_payload() -> None:
    ctx = _ctx_with_action(("draft", "active"), {"changed_by": "actor"})
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active", actor="alice")
    ev = ctx.last_event("planning.item.state.changed")
    assert ev["payload"].get("changed_by") == "alice"


# ── action event_suffix ───────────────────────────────────────────────────────

def test_action_event_suffix_publishes_kind_event() -> None:
    cfg = FakeConfig()
    cfg._lifecycle_transitions[("task", "draft", "active")] = (
        "activate",
        {"event_suffix": "activated", "metadata": {}},
    )
    ctx = FakeContext(config=cfg)
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active")
    assert any(e["type"] == "task.activated" for e in ctx.events)


def test_action_event_suffix_fires_before_state_changed() -> None:
    cfg = FakeConfig()
    cfg._lifecycle_transitions[("task", "draft", "active")] = (
        "activate",
        {"event_suffix": "activated", "metadata": {}},
    )
    ctx = FakeContext(config=cfg)
    ctx.add_item("t-1", "task", state="draft")
    StateMachine(ctx).state("t-1", "active")
    types = [e["type"] for e in ctx.events]
    assert types.index("task.activated") < types.index("planning.item.state.changed")


# ── apply_action ─────────────────────────────────────────────────────────────

def test_apply_action_delegates_to_transition_to() -> None:
    cfg = FakeConfig()
    cfg._actions["archive"] = {"transition_to": "cancelled"}
    ctx = FakeContext(config=cfg)
    ctx.add_item("t-1", "task", state="active")
    StateMachine(ctx).apply_action("archive", "t-1")
    assert ctx.items["t-1"].data["state"] == "cancelled"


def test_apply_action_missing_transition_to_raises() -> None:
    cfg = FakeConfig()
    cfg._actions["noop"] = {}
    ctx = FakeContext(config=cfg)
    ctx.add_item("t-1", "task", state="draft")
    with pytest.raises(ValueError, match="transition_to"):
        StateMachine(ctx).apply_action("noop", "t-1")


# ── is_terminal ───────────────────────────────────────────────────────────────

def test_is_terminal_true_for_done() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="done")
    assert StateMachine(ctx).is_terminal("t-1") is True


def test_is_terminal_false_for_active() -> None:
    ctx = _make_ctx()
    ctx.add_item("t-1", "task", state="active")
    assert StateMachine(ctx).is_terminal("t-1") is False


def test_is_terminal_true_for_missing_item() -> None:
    ctx = _make_ctx()
    assert StateMachine(ctx).is_terminal("nonexistent") is True


# ── cascade ───────────────────────────────────────────────────────────────────

def test_cascade_transitions_matching_kind() -> None:
    cfg = FakeConfig()
    cfg._lifecycle_transitions[("plan", "active", "cancelled")] = (
        "cancel",
        {
            "metadata": {},
            "cascade": {"by_kind": {"plan": {"task": "cancelled"}}},
        },
    )
    ctx = FakeContext(config=cfg)
    ctx.add_item("plan-1", "plan", state="active")
    ctx.add_item("t-1", "task", state="active")
    ctx.add_item("t-2", "task", state="active")
    StateMachine(ctx).state("plan-1", "cancelled")
    assert ctx.items["t-1"].data["state"] == "cancelled"
    assert ctx.items["t-2"].data["state"] == "cancelled"


def test_cascade_skips_terminal_items() -> None:
    cfg = FakeConfig()
    cfg._lifecycle_transitions[("plan", "active", "cancelled")] = (
        "cancel",
        {
            "metadata": {},
            "cascade": {"by_kind": {"plan": {"task": "cancelled"}}},
        },
    )
    ctx = FakeContext(config=cfg)
    ctx.add_item("plan-1", "plan", state="active")
    ctx.add_item("t-done", "task", state="done")
    StateMachine(ctx).state("plan-1", "cancelled")
    assert ctx.items["t-done"].data["state"] == "done"


def test_cascade_passes_depth_one_when_no_prior_metadata() -> None:
    """Cascade without prior metadata must publish event with propagation_depth=1."""
    cfg = FakeConfig()
    cfg._lifecycle_transitions[("plan", "active", "cancelled")] = (
        "cancel",
        {"metadata": {}, "cascade": {"by_kind": {"plan": {"task": "cancelled"}}}},
    )
    ctx = FakeContext(config=cfg)
    ctx.add_item("plan-1", "plan", state="active")
    ctx.add_item("t-1", "task", state="active")
    StateMachine(ctx).state("plan-1", "cancelled")
    # The cascade state change for t-1 emits planning.item.state.changed with the
    # cascade metadata merged into event_metadata.
    t1_events = [
        e for e in ctx.events
        if e["type"] == "planning.item.state.changed"
        and e["payload"].get("id") == "t-1"
    ]
    assert t1_events, "No state.changed event for t-1"
    assert t1_events[0]["metadata"].get("propagation_depth") == 1


def test_cascade_increments_depth_from_incoming_metadata() -> None:
    """Cascade with metadata depth=2 must publish event with propagation_depth=3."""
    cfg = FakeConfig()
    cfg._lifecycle_transitions[("plan", "active", "cancelled")] = (
        "cancel",
        {"metadata": {}, "cascade": {"by_kind": {"plan": {"task": "cancelled"}}}},
    )
    ctx = FakeContext(config=cfg)
    ctx.add_item("plan-1", "plan", state="active")
    ctx.add_item("t-1", "task", state="active")
    StateMachine(ctx).state("plan-1", "cancelled", metadata={"propagation_depth": 2})
    t1_events = [
        e for e in ctx.events
        if e["type"] == "planning.item.state.changed"
        and e["payload"].get("id") == "t-1"
    ]
    assert t1_events, "No state.changed event for t-1"
    assert t1_events[0]["metadata"].get("propagation_depth") == 3


def test_cascade_depth_flows_through_two_level_chain() -> None:
    """Depth increments at every hop in a multi-level cascade chain.

    plan→cancelled cascades task→cancelled; task→cancelled cascades subtask→cancelled.
    Without depth threading the second hop would carry no depth, breaking any
    host-side depth guard.  With threading: plan=0, task=1, subtask=2.
    """
    cfg = FakeConfig()
    cfg._lifecycle_transitions[("plan", "active", "cancelled")] = (
        "cancel",
        {"metadata": {}, "cascade": {"by_kind": {"plan": {"task": "cancelled"}}}},
    )
    cfg._lifecycle_transitions[("task", "active", "cancelled")] = (
        "cancel",
        {"metadata": {}, "cascade": {"by_kind": {"task": {"subtask": "cancelled"}}}},
    )
    ctx = FakeContext(config=cfg)
    ctx.add_item("plan-1", "plan", state="active")
    ctx.add_item("t-1", "task", state="active")
    ctx.add_item("sub-1", "subtask", state="active")

    StateMachine(ctx).state("plan-1", "cancelled")

    def _depth_for(item_id: str) -> int | None:
        events = [
            e for e in ctx.events
            if e["type"] == "planning.item.state.changed"
            and e["payload"].get("id") == item_id
        ]
        return (events[0]["metadata"] or {}).get("propagation_depth") if events else None

    assert ctx.items["t-1"].data["state"] == "cancelled"
    assert ctx.items["sub-1"].data["state"] == "cancelled"
    assert _depth_for("t-1") == 1
    assert _depth_for("sub-1") == 2


def test_cascade_logs_not_swallows_on_invalid_transition() -> None:
    """Cascade skips items where the target transition is disallowed — no raise."""
    cfg = FakeConfig()
    cfg._lifecycle_transitions[("plan", "active", "cancelled")] = (
        "cancel",
        {
            "metadata": {},
            # "done" is not reachable from "draft" (draft->active->done), so cascade should skip
            "cascade": {"by_kind": {"plan": {"task": "done"}}},
        },
    )
    ctx = FakeContext(config=cfg)
    ctx.add_item("plan-1", "plan", state="active")
    ctx.add_item("t-1", "task", state="draft")
    sm = StateMachine(ctx)
    sm.state("plan-1", "cancelled")
    assert ctx.items["t-1"].data["state"] == "draft"
