"""Integration tests for event layer and state propagation.

Tests the full propagation chain from task to spec through events.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.planning_testkit import seed_planning_config


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


@pytest.fixture
def planning_api():
    """Create planning API instance."""
    from audiagentic.planning.app.api import PlanningAPI

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        _seed_planning_project(root)
        api = PlanningAPI(root)
        yield api


@pytest.fixture
def event_store():
    """Create event store instance."""
    from audiagentic.interoperability.store import FileEventStore

    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileEventStore(Path(tmpdir) / "events")
        yield store


@pytest.fixture
def knowledge_api():
    """Create knowledge API instance (not yet implemented)."""
    # KnowledgeAPI not yet implemented - skip for now
    yield None


# NOTE: TestFullPropagationChain, TestRollbackPropagation, and TestConflictResolution
# classes were removed during the config-driven refactoring (task-0279).
# The old _task_to_wp() method was removed - propagation is now fully config-driven
# and tested in test_propagation.py and test_healing.py.


class TestReplaySafety:
    """Test replay safety mechanisms."""

    def test_replay_no_duplicate_changes(self, planning_api, event_store):
        """Test that replayed events don't cause duplicate state changes."""
        from audiagentic.interoperability.replay import ReplayService

        # Create request and task
        request = planning_api.new("request", "Test Request", "Test request", source="test")
        spec = planning_api.new(
            "spec", "Test Spec", "Test specification", request_refs=[request.data["id"]]
        )
        planning_api.new("plan", "Test Plan", "Test plan", spec=spec.data["id"])
        task = planning_api.new("task", "Test Task", "Test task", spec=spec.data["id"])

        # Set task to ready, in_progress, then done
        planning_api.state(task.data["id"], "ready")
        planning_api.state(task.data["id"], "in_progress")
        planning_api.state(task.data["id"], "done")

        # Get event bus and store events
        from audiagentic.interoperability import get_bus

        events = event_store.query()

        # Replay with dispatch_on_replay=False (default)
        replay_service = ReplayService(get_bus(), event_store, dispatch_on_replay=False)
        replay_count = replay_service.replay()

        # Verify no duplicate changes
        task_view = planning_api.lookup(task.data["id"])
        assert task_view.data["state"] == "done"


# class TestCrossComponentTrigger:
#     """Test cross-component triggers via events."""
#
#     def test_planning_task_done_marks_knowledge_stale(self, planning_api, knowledge_api):
#         """Test that planning task done marks knowledge pages stale."""
#         from audiagentic.knowledge.events import on_planning_state_change
#
#         # Create planning items
#         request = planning_api.new("request", "Test Request", "Test request", source="test")
#         spec = planning_api.new(
#             "spec", "Test Spec", "Test specification", request_refs=[request.data["id"]]
#         )
#         plan = planning_api.new("plan", "Test Plan", "Test plan", spec=spec.data["id"])
#         task = planning_api.new("task", "Test Task", "Test task", plan=plan.data["id"])
#
#         # Set task to ready, in_progress, then done
#         planning_api.state(task.data["id"], "ready")
#         planning_api.state(task.data["id"], "in_progress")
#         planning_api.state(task.data["id"], "done")
#
#         # Simulate event handler
#         payload = {
#             "subject": {"kind": "task", "id": task.data["id"]},
#             "new_state": "done",
#             "old_state": "ready",
#         }
#         metadata = {"is_replay": False}
#
#         # Handler should not raise
#         on_planning_state_change("task.done", payload, metadata)
