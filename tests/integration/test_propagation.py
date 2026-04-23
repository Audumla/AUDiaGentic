"""Integration tests for state propagation with event subscription.

Tests automatic state propagation across planning hierarchies via event subscription.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import pytest

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
    """Seed state propagation config."""
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
        rule: parent_in_set
        when:
          state_set: initial
        new_state: in_progress
      done:
        rule: all_children_in_set
        when:
          state_set: complete
        new_state: done
      blocked:
        rule: parent_not_in_set
        when:
          state_set: terminal
        new_state: blocked

  wp:
    enabled: true
    parent_kind: plan
    parent_field: plan_ref
    state_rules:
      in_progress:
        rule: parent_in_set
        when:
          state_set: initial
        new_state: in_progress
      done:
        rule: all_children_in_set
        when:
          state_set: complete
        new_state: done
      blocked:
        rule: parent_not_in_set
        when:
          state_set: terminal
        new_state: blocked

  plan:
    enabled: true
    parent_kind: spec
    parent_field: spec_refs
    state_rules:
      in_progress:
        rule: parent_in_set
        when:
          state_set: initial
        new_state: in_progress
      done:
        rule: all_children_in_set
        when:
          state_set: complete
        new_state: done
      blocked:
        rule: parent_not_in_set
        when:
          state_set: terminal
        new_state: blocked

  spec:
    enabled: true
    parent_kind: request
    parent_field: request_refs
    state_rules:
      in_progress:
        rule: parent_in_set
        when:
          state_set: initial
        new_state: in_progress
      done:
        rule: all_children_in_set
        when:
          state_set: complete
        new_state: done
        actions:
          - action: complete_parent
            parent_field: request_refs
            required_state_set: complete
            parent_blocking_set: terminal
            target_state: closed
      blocked:
        rule: parent_not_in_set
        when:
          state_set: terminal
        new_state: blocked

  request:
    enabled: false
    parent_kind: null
    state_rules:
      done:
        rule: none
        new_state: null

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
  none:
    enabled: true
    description: "No state propagation"
    logic: "audiagentic.planning.app.propagation_rules.rule_none"

  parent_in_set:
    enabled: true
    description: "Set parent to new_state when parent is in configured state set"
    logic: "audiagentic.planning.app.propagation_rules.rule_parent_in_set"

  all_children_in_set:
    enabled: true
    description: "Set parent to new_state when all sibling children are in configured state set"
    logic: "audiagentic.planning.app.propagation_rules.rule_all_children_in_set"

  parent_not_in_set:
    enabled: true
    description: "Set parent to new_state when parent is not in configured state set"
    logic: "audiagentic.planning.app.propagation_rules.rule_parent_not_in_set"

actions:
  complete_parent:
    enabled: true
    description: "Complete parent when all related children are in configured state set"
    logic: "audiagentic.planning.app.propagation_rules.action_complete_parent"
""")


def _wait_for_propagation(planning_api: PlanningAPI, timeout: float = 5.0) -> None:
    """Wait for async propagation to complete.

    Args:
        planning_api: PlanningAPI instance
        timeout: Maximum time to wait in seconds
    """
    from audiagentic.interoperability.queue import AsyncQueue

    queue = AsyncQueue.get_instance()
    start_time = time.time()
    while queue.size() > 0 and (time.time() - start_time) < timeout:
        time.sleep(0.1)


def _read_propagation_log(root: Path) -> list[dict]:
    path = root / ".audiagentic" / "planning" / "meta" / "propagation_log.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


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
    wp = planning_api.new("wp", label="Test WP", summary="Test work package", plan=plan_id)
    wp_id = wp.data["id"]
    task = planning_api.new("task", label="Test Task", summary="Test task", spec=spec_id)
    task_id = task.data["id"]
    planning_api.relink(wp_id, "task_refs", task_id)
    return request_id, spec_id, plan_id, wp_id, task_id


class TestStatePropagationIntegration:
    """Integration tests for state propagation engine."""

    @pytest.fixture(autouse=True)
    def reset_event_bus(self):
        """Reset event bus singleton before each test for isolation."""
        from audiagentic.interoperability import get_bus, reset_bus

        reset_bus()
        # Create a fresh bus for this test
        bus = get_bus()
        yield bus
        reset_bus()

    @pytest.fixture
    def planning_root(self, tmp_path: Path):
        """Create a temporary project directory with planning items."""
        # Reset bus before creating PlanningAPI so they share the same instance
        from audiagentic.interoperability import reset_bus

        reset_bus()
        _seed_planning_project(tmp_path)
        _seed_propagation_config(tmp_path)
        return tmp_path, PlanningAPI(tmp_path)

    def test_task_to_wp_propagation(self, planning_root):
        """Test task state propagation to WP."""
        _, planning_api = planning_root
        _, _, _, wp_id, task_id = _create_task_hierarchy(planning_api)
        # Transition WP to ready first (required for trigger_parent_if_ready rule)
        planning_api.state(wp_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        # Transition task to ready
        planning_api.state(task_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        # Transition task to in_progress (should propagate to WP)
        planning_api.state(task_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        wp_view = planning_api.lookup(wp_id)
        assert wp_view is not None
        assert wp_view.data["state"] == "in_progress"

    def test_wp_to_plan_propagation(self, planning_root):
        """Test WP state propagation to Plan."""
        root, planning_api = planning_root
        _, _, plan_id, wp_id, _ = _create_task_hierarchy(planning_api)
        # Transition plan to ready first (required for trigger_parent_if_ready rule)
        planning_api.state(plan_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        # Transition WP to ready
        planning_api.state(wp_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        # Transition WP to in_progress (should propagate to plan)
        planning_api.state(wp_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        plan_view = planning_api.lookup(plan_id)
        assert plan_view is not None
        assert plan_view.data["state"] == "in_progress"
        assert any(
            entry.get("target_id") == plan_id and entry.get("status") == "success"
            for entry in _read_propagation_log(root)
        )

    def test_plan_to_spec_propagation(self, planning_root):
        """Test Plan state propagation to Spec."""
        _, planning_api = planning_root
        _, spec_id = _create_request_and_spec(planning_api)
        plan = planning_api.new("plan", label="Test Plan", summary="Test plan", spec=spec_id)
        plan_id = plan.data["id"]
        # Transition spec to ready first (required for trigger_parent_if_ready rule)
        planning_api.state(spec_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        # Transition plan to ready
        planning_api.state(plan_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        # Transition plan to in_progress (should propagate to spec)
        planning_api.state(plan_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        spec_view = planning_api.lookup(spec_id)
        assert spec_view is not None
        assert spec_view.data["state"] == "in_progress"

    def test_spec_to_request_propagation(self, planning_root):
        """Test Spec state propagation to Request."""
        _, planning_api = planning_root
        request_id, spec_id = _create_request_and_spec(planning_api)
        # Request uses "captured" as initial state, not "ready"
        # Transition request to distilled (equivalent to ready for requests)
        planning_api.state(request_id, "distilled", metadata={})
        _wait_for_propagation(planning_api)
        # Transition spec to ready
        planning_api.state(spec_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        # Transition spec to in_progress (should propagate to request)
        planning_api.state(spec_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        request_view = planning_api.lookup(request_id)
        assert request_view is not None
        # Request state machine doesn't have in_progress, so it stays in distilled
        # The propagation rule tries to set in_progress but request workflow doesn't allow it
        assert request_view.data["state"] == "distilled"

    def test_full_hierarchy_propagation(self, planning_root):
        """Test state propagation through full hierarchy."""
        _, planning_api = planning_root
        request_id, spec_id, plan_id, wp_id, task_id = _create_task_hierarchy(planning_api)
        # Transition all items to ready first (required for trigger_parent_if_ready rule)
        planning_api.state(request_id, "distilled", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(spec_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(plan_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(wp_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(task_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        # Transition task to in_progress (should propagate up the hierarchy)
        planning_api.state(task_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        wp_view = planning_api.lookup(wp_id)
        assert wp_view.data["state"] == "in_progress"
        plan_view = planning_api.lookup(plan_id)
        assert plan_view.data["state"] == "in_progress"
        spec_view = planning_api.lookup(spec_id)
        assert spec_view.data["state"] == "in_progress"
        request_view = planning_api.lookup(request_id)
        # Request state machine doesn't have in_progress, so it stays in distilled
        assert request_view.data["state"] == "distilled"

    def test_propagation_disabled_globally(self, tmp_path: Path):
        """Test that propagation is disabled when globally disabled."""
        _seed_planning_project(tmp_path)
        # Override config to disable propagation
        config_dir = tmp_path / ".audiagentic" / "planning" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "state_propagation.yaml"
        config_file.write_text("""
global:
  enabled: false
  max_depth: 10
  default_mode: sync
kinds: {}
terminal_states: [done, archived]
state_priority: {}
""")
        planning_api = PlanningAPI(tmp_path)
        _, _, _, wp_id, task_id = _create_task_hierarchy(planning_api)
        planning_api.state(wp_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(task_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(task_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        wp_view = planning_api.lookup(wp_id)
        assert wp_view.data["state"] == "ready"

    def test_propagation_respects_terminal_states(self, planning_root):
        """Test that propagation respects terminal states."""
        _, planning_api = planning_root
        _, _, _, wp_id, task_id = _create_task_hierarchy(planning_api)
        # Transition WP to done (draft -> ready -> in_progress -> done)
        planning_api.state(wp_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(wp_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(wp_id, "done", metadata={})
        _wait_for_propagation(planning_api)
        # Transition task to in_progress (should NOT propagate because WP is in terminal state)
        planning_api.state(task_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(task_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        wp_view = planning_api.lookup(wp_id)
        assert wp_view.data["state"] == "done"

    def test_cycle_detection_with_max_depth(self, tmp_path: Path):
        """Test that cycle detection prevents infinite loops."""
        _seed_planning_project(tmp_path)
        _seed_propagation_config(tmp_path)
        planning_api = PlanningAPI(tmp_path)
        config = planning_api._propagation_engine.load_workflow_config()
        config["global"]["max_depth"] = 2
        planning_api._propagation_engine._config = config
        _, spec_id = _create_request_and_spec(planning_api)
        plan = planning_api.new("plan", label="Test Plan", summary="Test plan", spec=spec_id)
        plan_id = plan.data["id"]
        # Transition spec to ready first
        planning_api.state(spec_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        # Call handler with propagation_depth exceeding max_depth
        metadata = {"propagation_depth": 3}
        planning_api._on_state_change_for_propagation(
            "planning.item.state.changed",
            {"id": plan_id, "old_state": "ready", "new_state": "in_progress"},
            metadata,
        )
        spec_view = planning_api.lookup(spec_id)
        # Spec should remain in ready state because propagation was blocked by max_depth
        assert spec_view.data["state"] == "ready"

    def test_propagation_failure_isolation(self, planning_root):
        """Test that propagation failures don't break original state changes."""
        _, planning_api = planning_root
        _, _, _, _, task_id = _create_task_hierarchy(planning_api)
        # Transition task to in_progress (draft -> ready -> in_progress)
        planning_api.state(task_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(task_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        task_view = planning_api.lookup(task_id)
        assert task_view.data["state"] == "in_progress"

    def test_done_propagation_skips_invalid_parent_transition(self, planning_root, caplog):
        """Done propagation should skip invalid parent workflow jumps without subscriber errors."""
        root, planning_api = planning_root
        _, _, _, wp_id, task_id = _create_task_hierarchy(planning_api)

        with caplog.at_level(logging.ERROR, logger="audiagentic.interoperability.bus"):
            planning_api.state(task_id, "ready", metadata={})
            _wait_for_propagation(planning_api)
            planning_api.state(task_id, "in_progress", metadata={})
            _wait_for_propagation(planning_api)
            planning_api.state(task_id, "done", metadata={})
            _wait_for_propagation(planning_api)

        wp_view = planning_api.lookup(wp_id)
        assert wp_view is not None
        assert wp_view.data["state"] == "draft"
        assert not any(
            "invalid transition draft -> done" in record.getMessage() for record in caplog.records
        )
        assert any(
            entry.get("target_id") == wp_id
            and entry.get("status") == "skipped"
            and entry.get("reason") == "invalid_transition"
            for entry in _read_propagation_log(root)
        )

    def test_done_propagates_through_direct_parent_ref(self, planning_root):
        """Completion propagation works when child stores the parent ref directly."""
        _, planning_api = planning_root
        _, _, plan_id, wp_id, _ = _create_task_hierarchy(planning_api)

        planning_api.state(plan_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(plan_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(wp_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(wp_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(wp_id, "done", metadata={})
        _wait_for_propagation(planning_api)

        plan_view = planning_api.lookup(plan_id)
        assert plan_view is not None
        assert plan_view.data["state"] == "done"

    def test_request_completion_uses_rel_list_and_runs_once(self, planning_root):
        """Parent completion action supports rel-list refs and avoids duplicate attempts."""
        root, planning_api = planning_root
        request_id, spec_id = _create_request_and_spec(planning_api)

        planning_api.state(request_id, "distilled", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(spec_id, "ready", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(spec_id, "in_progress", metadata={})
        _wait_for_propagation(planning_api)
        planning_api.state(spec_id, "done", metadata={})
        _wait_for_propagation(planning_api)

        request_view = planning_api.lookup(request_id)
        assert request_view is not None
        assert request_view.data["state"] == "closed"

        matching = [
            entry
            for entry in _read_propagation_log(root)
            if entry.get("target_id") == request_id
            and entry.get("new_state") == "closed"
            and entry.get("status") == "success"
        ]
        assert len(matching) == 1
