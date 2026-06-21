"""Unit tests for foundation/workflow/propagation/engine.py.

Tests use FakeContext exclusively — zero dependency on host components.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.workflow.propagation.engine import StatePropagationEngine

from .conftest import FakeContext

# ── engine factory ────────────────────────────────────────────────────────────

def _minimal_config(max_depth: int = 10, enabled: bool = True) -> dict:
    """Config with task->plan propagation: task done -> plan done (all_children_in_set)."""
    return {
        "global": {"enabled": enabled, "max_depth": max_depth},
        "kinds": {
            "task": {
                "enabled": True,
                "parent_kind": "plan",
                "parent_field": "task_refs",
                "state_rules": {
                    "done": {
                        "rule": "all_children_in_set",
                        "when": {"state_set": "complete"},
                        "new_state": "done",
                    }
                },
            }
        },
        "rules": {
            "all_children_in_set": {
                "enabled": True,
                "logic": "audiagentic.foundation.workflow.propagation.rules.rule_all_children_in_set",
            }
        },
        "actions": {},
    }


def _engine(ctx: FakeContext, config: dict | None = None, tmp_path: Path | None = None) -> StatePropagationEngine:
    import tempfile
    from pathlib import Path

    import yaml

    cfg = config or _minimal_config()
    root = tmp_path or Path(tempfile.mkdtemp())
    p = root / "propagation.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    log_path = root / ".audiagentic" / "workflow" / "meta" / "propagation_log.jsonl"
    return StatePropagationEngine(ctx=ctx, enabled=True, config_path=p, log_path=log_path)


# ── constructor guards ────────────────────────────────────────────────────────

def test_enabled_without_config_path_raises() -> None:
    with pytest.raises(AudiaGenticError, match="config_path"):
        StatePropagationEngine(ctx=FakeContext(), enabled=True, config_path=None)


def test_disabled_without_config_path_ok() -> None:
    engine = StatePropagationEngine(ctx=FakeContext(), enabled=False, config_path=None)
    assert engine.propagate("any", "done") == []


# ── propagate guards ──────────────────────────────────────────────────────────

def test_propagate_when_disabled_returns_empty() -> None:
    engine = StatePropagationEngine(ctx=FakeContext(), enabled=False, config_path=None)
    assert engine.propagate("t-1", "done") == []


def test_propagate_healing_fix_flag_returns_empty() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx)
    assert engine.propagate("t-1", "done", metadata={"healing_fix": True}) == []


def test_propagate_at_max_depth_returns_empty() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx, _minimal_config(max_depth=3))
    result = engine.propagate("t-1", "done", metadata={"propagation_depth": 3})
    assert result == []


def test_propagate_global_disabled_returns_empty() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx, _minimal_config(enabled=False))
    assert engine.propagate("t-1", "done") == []


def test_propagate_kind_disabled_returns_empty() -> None:
    cfg = _minimal_config()
    cfg["kinds"]["task"]["enabled"] = False
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx, cfg)
    assert engine.propagate("t-1", "done") == []


def test_propagate_per_item_override_disabled_returns_empty() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="done", propagation={"enabled": False})
    engine = _engine(ctx)
    assert engine.propagate("t-1", "done") == []


def test_propagate_rule_none_returns_empty() -> None:
    cfg = _minimal_config()
    cfg["kinds"]["task"]["state_rules"]["done"]["rule"] = "none"
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx, cfg)
    assert engine.propagate("t-1", "done") == []


def test_propagate_unknown_item_returns_empty() -> None:
    ctx = FakeContext()
    engine = _engine(ctx)
    assert engine.propagate("ghost", "done") == []


# ── propagate success ─────────────────────────────────────────────────────────

def test_propagate_returns_parent_triple_when_rule_passes() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx)
    result = engine.propagate("t-1", "done")
    assert ("p-1", "plan", "done") in result


def test_propagate_deduplicates_results() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx)
    result = engine.propagate("t-1", "done")
    assert result.count(("p-1", "plan", "done")) == 1


def test_propagate_deduplicates_same_triple_from_multiple_sources() -> None:
    """Rule + action both producing the same triple independently → one entry in output.

    This is the real dedupe scenario: two independent code paths suggest the same
    propagation. This test pins the contract so any future regression is caught.
    Config with callables is injected directly to bypass YAML serialization.
    """
    def _always_true(*args, **kw) -> bool:
        return True

    def _return_same_triple(engine, item_id, action_entry, state_rules):
        return [("p-1", "plan", "done")]

    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx)
    # Inject callable config directly — bypasses YAML round-trip
    engine._workflow_config = {
        "global": {"enabled": True, "max_depth": 10},
        "kinds": {
            "task": {
                "enabled": True,
                "parent_kind": "plan",
                "parent_field": "task_refs",
                "state_rules": {
                    "done": {
                        "rule": "always_true",
                        "when": {"state_set": "complete"},
                        "new_state": "done",
                        "actions": [{"action": "also_done"}],
                    }
                },
            }
        },
        "rules": {"always_true": {"enabled": True, "logic": _always_true}},
        "actions": {"also_done": {"enabled": True, "logic": _return_same_triple}},
    }
    result = engine.propagate("t-1", "done")
    # rule adds ("p-1","plan","done") AND action adds ("p-1","plan","done") → dedupe to 1
    assert result.count(("p-1", "plan", "done")) == 1


def test_propagate_no_parents_returns_empty() -> None:
    ctx = FakeContext()
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx)
    assert engine.propagate("t-1", "done") == []


# ── apply_propagation guards ──────────────────────────────────────────────────

def test_apply_propagation_target_not_found_logs_and_returns() -> None:
    ctx = FakeContext()
    ctx.add_item("s-1", "task", state="done")
    engine = _engine(ctx)
    engine.apply_propagation("ghost", "done", "s-1", "done", {})
    assert ctx.items == {"s-1": ctx.items["s-1"]}


def test_apply_propagation_already_in_target_state_skips() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="done")
    ctx.add_item("s-1", "task", state="done")
    engine = _engine(ctx)
    engine.apply_propagation("p-1", "done", "s-1", "done", {})
    assert ctx.saved == []


def test_apply_propagation_invalid_transition_skips() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="draft")
    ctx.add_item("s-1", "task", state="done")
    engine = _engine(ctx)
    engine.apply_propagation("p-1", "cancelled", "s-1", "done", {})
    # draft -> cancelled is not a valid transition in FakeConfig
    assert ctx.items["p-1"].data["state"] == "draft"


def test_apply_propagation_invalid_transition_logs_normalized_reason(tmp_path: Path) -> None:
    ctx = FakeContext()
    ctx.root = tmp_path
    ctx.add_item("p-1", "plan", state="draft")
    ctx.add_item("s-1", "task", state="done")
    engine = _engine(ctx, tmp_path=tmp_path)
    engine.apply_propagation("p-1", "cancelled", "s-1", "done", {})

    log_path = tmp_path / ".audiagentic" / "workflow" / "meta" / "propagation_log.jsonl"
    entries = [
        json.loads(line)
        for line in log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert entries[-1]["attributes"]["workflow.reason"] == "invalid_transition"


def test_apply_propagation_lower_priority_state_skips() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="done")  # priority 20
    ctx.add_item("s-1", "task", state="done")
    engine = _engine(ctx)
    # active has priority 10 < done (20)
    engine.apply_propagation("p-1", "active", "s-1", "done", {})
    assert ctx.items["p-1"].data["state"] == "done"


def test_apply_propagation_at_max_depth_skips() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active")
    ctx.add_item("s-1", "task", state="done")
    engine = _engine(ctx, _minimal_config(max_depth=2))
    engine.apply_propagation("p-1", "done", "s-1", "done", {"propagation_depth": 2})
    assert ctx.items["p-1"].data["state"] == "active"


def test_apply_propagation_succeeds_and_calls_state() -> None:
    ctx = FakeContext()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx)
    engine.apply_propagation("p-1", "done", "t-1", "done", {})
    assert ctx.items["p-1"].data["state"] == "done"


def test_apply_propagation_delegates_validation_to_ctx_state() -> None:
    """Engine must not pre-validate transitions — ctx.state() is always called.

    Old code had _valid_transition() which returned early without ever calling
    ctx.state().  New code removes that pre-check: ctx.state() is called and its
    ValueError is caught.  This test fails on any code that skips ctx.state().
    """
    calls: list[tuple[str, str]] = []

    class TrackingCtx(FakeContext):
        def state(self, id_: str, new_state: str, *, metadata=None, **kw):
            calls.append((id_, new_state))
            return super().state(id_, new_state, metadata=metadata, **kw)

    ctx = TrackingCtx()
    ctx.add_item("p-1", "plan", state="draft")
    ctx.add_item("s-1", "task", state="done")
    engine = _engine(ctx)
    engine.apply_propagation("p-1", "cancelled", "s-1", "done", {})
    # ctx.state must have been called even though draft→cancelled is invalid
    assert ("p-1", "cancelled") in calls


def test_apply_propagation_value_error_from_ctx_state_is_swallowed() -> None:
    """ValueError raised by ctx.state is treated as a skip, not a hard failure.

    Old code had ``except Exception: raise`` which would have re-raised ValueError.
    New code has ``except ValueError: return`` — this test fails on the old handler.
    """
    class RaisingCtx(FakeContext):
        def state(self, id_: str, new_state: str, *, metadata=None, **kw):
            raise ValueError("transition rejected by host")

    ctx = RaisingCtx()
    ctx.add_item("p-1", "plan", state="active")  # active→done is a valid transition
    ctx.add_item("s-1", "task", state="done")
    engine = _engine(ctx)
    # ctx.state raises ValueError for a *valid* transition path — must not propagate
    engine.apply_propagation("p-1", "done", "s-1", "done", {})
    assert ctx.items["p-1"].data["state"] == "active"


def test_apply_propagation_non_value_error_from_ctx_state_propagates() -> None:
    """Non-ValueError from ctx.state (e.g. storage failure) must re-raise."""
    class BrokenCtx(FakeContext):
        def state(self, id_: str, new_state: str, *, metadata=None, **kw):
            raise RuntimeError("storage failure")

    ctx = BrokenCtx()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx)
    with pytest.raises(RuntimeError, match="storage failure"):
        engine.apply_propagation("p-1", "done", "t-1", "done", {})


def test_apply_propagation_increments_depth_in_metadata() -> None:
    """Propagation chain: each apply_propagation bumps propagation_depth."""
    captured: list[dict] = []

    class TrackingCtx(FakeContext):
        def state(self, id_: str, new_state: str, *, metadata=None, **kw):
            captured.append(dict(metadata or {}))
            return super().state(id_, new_state, metadata=metadata, **kw)

    ctx = TrackingCtx()
    ctx.add_item("p-1", "plan", state="active", task_refs=["t-1"])
    ctx.add_item("t-1", "task", state="done")
    engine = _engine(ctx)
    engine.apply_propagation("p-1", "done", "t-1", "done", {"propagation_depth": 1})
    assert captured[0]["propagation_depth"] == 2
