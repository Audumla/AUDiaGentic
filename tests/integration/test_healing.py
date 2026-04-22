"""Integration tests for state healing functionality.

Tests validation and auto-healing of state inconsistencies.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.planning_testkit import seed_planning_config

from audiagentic.planning.app.api import PlanningAPI


def _seed_planning_project(root: Path) -> None:
    """Seed the minimum planning config needed for PlanningAPI."""
    seed_planning_config(root)
    for d in (
        "requests",
        "specifications",
        "plans",
        "tasks/core",
        "work-packages/core",
        "standards",
    ):
        (root / "docs" / "planning" / d).mkdir(parents=True, exist_ok=True)


def _seed_propagation_config(root: Path) -> None:
    """Seed state propagation config with healing enabled."""
    config_dir = root / ".audiagentic" / "planning" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "state_propagation.yaml"
    config_file.write_text("""
global:
  enabled: true
  max_depth: 10
  default_mode: sync

kinds:
  task:
    enabled: true
    parent_kind: wp
    parent_field: task_refs
    state_rules:
      in_progress:
        rule: trigger_parent_if_ready
        new_state: in_progress
      done:
        rule: check_all_children_done
        new_state: done

  wp:
    enabled: true
    parent_kind: plan
    parent_field: plan_ref
    state_rules:
      in_progress:
        rule: trigger_parent_if_ready
        new_state: in_progress
      done:
        rule: check_all_children_done
        new_state: done

  plan:
    enabled: true
    parent_kind: spec
    parent_field: spec_refs
    state_rules: {}

  spec:
    enabled: true
    parent_kind: request
    parent_field: request_refs
    state_rules: {}

  request:
    enabled: false
    parent_kind: null
    state_rules: {}

terminal_states:
  - done
  - archived

state_priority:
  archived: 100
  done: 90
  blocked: 50
  in_progress: 20
  ready: 10

healing:
  enabled: true
  auto_fix: true
  log_only: false
  on_state_change: false
  max_fixes_per_run: 10

rules:
  trigger_parent_if_ready:
    enabled: true
    description: "Set parent to new_state if parent is ready"
    logic: "audiagentic.planning.app.propagation_rules.rule_trigger_parent_if_ready"
  check_all_children_done:
    enabled: true
    description: "Set to done if all children are done"
    logic: "audiagentic.planning.app.propagation_rules.rule_check_all_children_done"
  none:
    enabled: true
    description: "No state propagation"
    logic: "audiagentic.planning.app.propagation_rules.rule_none"
""")


def _create_request_and_spec(planning_api: PlanningAPI) -> tuple[str, str]:
    """Create minimal valid request/spec context for dependent items."""
    request = planning_api.new(
        "request", label="Test Request", summary="Test request", source="test"
    )
    request_id = request.data["id"]
    spec = planning_api.new(
        "spec", label="Test Spec", summary="Test specification", request_refs=[request_id]
    )
    return request_id, spec.data["id"]


def _create_task_hierarchy(planning_api: PlanningAPI) -> tuple[str, str, str, str, str]:
    """Create valid request -> spec -> plan -> wp -> task chain."""
    request_id, spec_id = _create_request_and_spec(planning_api)
    plan = planning_api.new("plan", label="Test Plan", summary="Test plan", spec=spec_id)
    plan_id = plan.data["id"]
    wp = planning_api.new("wp", label="Test WP", summary="Test WP", plan=plan_id)
    wp_id = wp.data["id"]
    task = planning_api.new("task", label="Test Task", summary="Test task", spec=spec_id)
    task_id = task.data["id"]
    planning_api.relink(wp_id, "task_refs", task_id)
    return request_id, spec_id, plan_id, wp_id, task_id


def test_heal_auto_fix(tmp_path: Path) -> None:
    """Test healing with auto_fix=True applies fixes."""
    _seed_planning_project(tmp_path)
    _seed_propagation_config(tmp_path)
    planning_api = PlanningAPI(tmp_path)
    _, _, _, wp_id, task_id = _create_task_hierarchy(planning_api)

    # Create inconsistency
    planning_api.state(task_id, "ready", metadata={})
    planning_api.state(task_id, "in_progress", metadata={})

    # Heal with auto_fix=True should apply fixes
    result = planning_api._propagation_engine.heal_hierarchy(task_id, auto_fix=True)
    assert len(result["errors"]) > 0
    assert len(result["fixes"]) > 0
    # At least one fix should be applied
    assert any(fix.get("applied", False) for fix in result["fixes"])

    # WP should now be in ready state
    wp_view = planning_api.lookup(wp_id)
    assert wp_view.data["state"] == "ready"


def test_validate_parent_done_child_not_done(tmp_path: Path) -> None:
    """Test validation detects parent done but child not done."""
    _seed_planning_project(tmp_path)
    _seed_propagation_config(tmp_path)
    planning_api = PlanningAPI(tmp_path)
    _, _, _, wp_id, task_id = _create_task_hierarchy(planning_api)

    # Transition WP to done but leave task in draft
    planning_api.state(wp_id, "ready", metadata={})
    planning_api.state(wp_id, "in_progress", metadata={})
    planning_api.state(wp_id, "done", metadata={})

    # Validate should detect inconsistency
    errors = planning_api._propagation_engine.validate_hierarchy(task_id)
    assert len(errors) > 0
    assert any("Parent is done but child is not" in e.get("error", "") for e in errors)


def test_heal_does_not_auto_fix_dangerous(tmp_path: Path) -> None:
    """Test healing does not auto-fix dangerous inconsistencies."""
    _seed_planning_project(tmp_path)
    _seed_propagation_config(tmp_path)
    planning_api = PlanningAPI(tmp_path)
    _, _, _, wp_id, task_id = _create_task_hierarchy(planning_api)

    # Create dangerous inconsistency (parent done, child not done)
    planning_api.state(wp_id, "ready", metadata={})
    planning_api.state(wp_id, "in_progress", metadata={})
    planning_api.state(wp_id, "done", metadata={})

    # Heal with auto_fix=True should NOT apply fix for dangerous inconsistency
    result = planning_api._propagation_engine.heal_hierarchy(task_id, auto_fix=True)
    assert len(result["errors"]) > 0
    assert len(result["fixes"]) > 0
    # Fixes should not be applied (can_auto_fix=False for this type)
    assert all(not fix.get("applied", False) for fix in result["fixes"])
    # Task should still be in draft
    task_view = planning_api.lookup(task_id)
    assert task_view.data["state"] == "draft"


def test_healing_fix_flag_prevents_propagation(tmp_path: Path) -> None:
    """Test that healing_fix flag in metadata prevents propagation loops."""
    _seed_planning_project(tmp_path)
    _seed_propagation_config(tmp_path)
    planning_api = PlanningAPI(tmp_path)
    _, _, _, wp_id, task_id = _create_task_hierarchy(planning_api)

    # Set up WP in ready state so propagation would normally trigger
    planning_api.state(wp_id, "ready", metadata={})

    # Call propagate with healing_fix flag - should return empty list
    propagations = planning_api._propagation_engine.propagate(
        task_id, "in_progress", metadata={"healing_fix": True}
    )
    assert propagations == []

    # Call propagate without healing_fix flag - should return propagations
    propagations = planning_api._propagation_engine.propagate(task_id, "in_progress", metadata={})
    # Should have at least one propagation (task -> wp)
    assert len(propagations) > 0


def test_max_depth_enforcement(tmp_path: Path) -> None:
    """Test that max_depth is enforced to prevent infinite propagation cycles."""
    _seed_planning_project(tmp_path)
    # Set max_depth to 2 for testing
    config_dir = tmp_path / ".audiagentic" / "planning" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "state_propagation.yaml"
    config_file.write_text("""
global:
  enabled: true
  max_depth: 2
  default_mode: sync

kinds:
  task:
    enabled: true
    parent_kind: wp
    parent_field: task_refs
    state_rules:
      in_progress:
        rule: trigger_parent_if_ready
        new_state: in_progress

  wp:
    enabled: true
    parent_kind: plan
    parent_field: plan_ref
    state_rules:
      in_progress:
        rule: trigger_parent_if_ready
        new_state: in_progress

  plan:
    enabled: true
    parent_kind: spec
    parent_field: spec_refs
    state_rules: {}

terminal_states:
  - done
  - archived

state_priority:
  archived: 100
  done: 90
  blocked: 50
  in_progress: 20
  ready: 10

rules:
  trigger_parent_if_ready:
    enabled: true
    description: "Set parent to new_state if parent is ready"
    logic: "audiagentic.planning.app.propagation_rules.rule_trigger_parent_if_ready"
  none:
    enabled: true
    description: "No state propagation"
    logic: "audiagentic.planning.app.propagation_rules.rule_none"

healing:
  enabled: true
  auto_fix: false
  log_only: true
  on_state_change: false
  max_fixes_per_run: 10
""")
    planning_api = PlanningAPI(tmp_path)

    # Create a chain: task -> wp -> plan
    _, _, plan_id, wp_id, task_id = _create_task_hierarchy(planning_api)

    # Set all to ready state
    planning_api.state(plan_id, "ready", metadata={})
    planning_api.state(wp_id, "ready", metadata={})

    # Try to propagate with depth exceeding max_depth
    # This should be prevented by max_depth check
    metadata_exceeding_depth = {
        "propagation_depth": 5,  # Exceeds max_depth of 2
        "correlation_id": "test-correlation",
    }

    # propagate() should return empty list when depth exceeds max
    propagations = planning_api._propagation_engine.propagate(
        task_id, "in_progress", metadata=metadata_exceeding_depth
    )
    assert propagations == []

    # apply_propagation() should also respect max_depth
    # (this is tested indirectly via the propagate check above)
