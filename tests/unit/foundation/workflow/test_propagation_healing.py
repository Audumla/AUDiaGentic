"""Unit tests for foundation/workflow/propagation/healing.py."""

from __future__ import annotations

from audiagentic.foundation.workflow.propagation import healing

from .conftest import FakeConfig, FakeContext

# ── engine stub ───────────────────────────────────────────────────────────────

class FakeEngine:
    def __init__(self, ctx: FakeContext, wf_config: dict | None = None) -> None:
        self.ctx = ctx
        self.config = ctx.config
        self.workflow_config = wf_config or {
            "kinds": {
                "task": {
                    "enabled": True,
                    "parent_kind": "plan",
                    "parent_field": "task_refs",
                }
            }
        }


# ── validate ──────────────────────────────────────────────────────────────────

def test_validate_item_not_found() -> None:
    ctx = FakeContext()
    engine = FakeEngine(ctx)
    errors = healing.validate(engine, "ghost")
    assert any("not found" in e.get("error", "") for e in errors)


def test_validate_item_no_kind() -> None:
    ctx = FakeContext()
    item = ctx.add_item("t-1", "task", state="draft")
    item.data.pop("state")
    engine = FakeEngine(ctx, {"kinds": {}})
    errors = healing.validate(engine, "t-1")
    assert errors == []


def test_validate_kind_not_configured_returns_empty() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="draft")
    engine = FakeEngine(ctx, {"kinds": {}})
    assert healing.validate(engine, "t-1") == []


def test_validate_kind_disabled_returns_empty() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="draft")
    engine = FakeEngine(ctx, {"kinds": {"task": {"enabled": False}}})
    assert healing.validate(engine, "t-1") == []


def test_validate_no_parent_configured_returns_empty() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="draft")
    engine = FakeEngine(ctx, {"kinds": {"task": {"enabled": True}}})
    assert healing.validate(engine, "t-1") == []


def test_validate_consistent_hierarchy_returns_empty() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="active")
    engine = FakeEngine(ctx)
    assert healing.validate(engine, "t-1") == []


def test_validate_parent_complete_child_active_reports_error() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="done", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="active")
    engine = FakeEngine(ctx)
    errors = healing.validate(engine, "t-1")
    assert any("complete" in e.get("error", "").lower() for e in errors)


def test_validate_parent_initial_child_active_reports_error() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="draft", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="active")
    engine = FakeEngine(ctx)
    errors = healing.validate(engine, "t-1")
    assert any("initial state" in e.get("error", "") for e in errors)


def test_validate_parent_not_found_reports_error() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="active", plan_ref="ghost")
    engine = FakeEngine(ctx, {
        "kinds": {"task": {"enabled": True, "parent_kind": "plan", "parent_field": "plan_ref"}}
    })
    errors = healing.validate(engine, "t-1")
    assert any("not found" in e.get("error", "").lower() for e in errors)


# ── heal ──────────────────────────────────────────────────────────────────────

def test_heal_no_errors_returns_empty_fixes() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="active")
    engine = FakeEngine(ctx)
    result = healing.heal(engine, "t-1")
    assert result["errors"] == []
    assert result["fixes"] == []


def test_heal_auto_fix_false_does_not_apply() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="draft", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="active")
    engine = FakeEngine(ctx)
    result = healing.heal(engine, "t-1", auto_fix=False)
    assert any(not fix.get("applied", False) for fix in result["fixes"])
    assert ctx.items["p-1"].data["state"] == "draft"


def test_heal_auto_fix_true_can_fix_applies_when_possible() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="draft", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="active")
    engine = FakeEngine(ctx)
    result = healing.heal(engine, "t-1", auto_fix=True)
    fixable = [f for f in result["fixes"] if f.get("can_auto_fix")]
    if fixable:
        assert fixable[0].get("applied") is True


def test_heal_dangerous_fix_never_auto_fixed() -> None:
    """Parent is complete but child is not — too dangerous to auto-fix."""
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="done", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="active")
    engine = FakeEngine(ctx)
    result = healing.heal(engine, "t-1", auto_fix=True)
    for fix in result["fixes"]:
        assert not fix.get("can_auto_fix"), "Dangerous fix should not be auto-fixable"


# ── _pick_parent_advance ─────────────────────────────────────────────────────

def test_pick_parent_advance_prefers_active_non_blocked_state() -> None:
    ctx = FakeContext()
    view = ctx.add_item("p-1", "plan", state="draft")
    assert healing._pick_parent_advance(ctx.config, view) == "active"


def test_pick_parent_advance_returns_none_when_no_transitions_and_no_states() -> None:
    cfg = FakeConfig()
    cfg._workflows["*"]["transitions"]["draft"] = []
    # Clear all state sets so every fallback path exhausts
    cfg._state_sets = {"initial": {"draft"}, "active": set(), "blocked": set(), "complete": set(), "terminal": set()}
    ctx = FakeContext(config=cfg)
    view = ctx.add_item("p-1", "plan", state="draft")
    result = healing._pick_parent_advance(ctx.config, view)
    assert result is None


# ── _suggest ─────────────────────────────────────────────────────────────────

def test_suggest_unknown_error_type_returns_manual_review() -> None:
    ctx = FakeContext()
    engine = FakeEngine(ctx)
    fix = healing._suggest(engine, {"error": "Unknown weird error"})
    assert "Manual review" in fix["suggestion"]
    assert fix["can_auto_fix"] is False
