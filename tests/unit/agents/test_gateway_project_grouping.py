"""One logical project groups its worktrees without moving checkout-owned records."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from audiagentic.components.agents.gateway import api, store
from audiagentic.components.agents.gateway.queue import queue as queue_mod
from audiagentic.components.agents.gateway.service import known_projects
from audiagentic.components.agents.gateway.service.application import GatewayServiceApplication
from audiagentic.components.agents.gateway.service.dashboard import dashboard_snapshot
from audiagentic.components.agents.gateway.service.dashboard_images import (
    project_group_image_id,
    project_image_id,
)
from audiagentic.components.agents.gateway.session import sessions
from audiagentic.components.project import project_api
from audiagentic.foundation.time import now_iso_z


def test_dashboard_aggregates_worktrees_but_retains_checkout_action_ids(tmp_path, monkeypatch):
    roots = [tmp_path / "main-checkout", tmp_path / "feature-one"]
    for root in roots:
        root.mkdir()
    stamp = datetime.now(timezone.utc)
    registry = SimpleNamespace(projects=tuple(
        known_projects.KnownProject(root, stamp, stamp, "compatible") for root in roots
    ))
    monkeypatch.setattr(known_projects, "load_known_projects", lambda _path: registry)
    monkeypatch.setattr(project_api, "project_id", lambda _root: ("AUDiaGentic", "settings"))
    monkeypatch.setattr(project_api, "resolve_project_name", lambda _root: "AUDiaGentic")
    monkeypatch.setattr(sessions, "peek_session_runtime", lambda: None)
    now = now_iso_z()
    monkeypatch.setattr(api, "list_dashboard_requests", lambda root: [{
        "request-id": f"req_example_{root.name}",
        "state": "completed",
        "created-at": now,
        "updated-at": now,
    }])
    monkeypatch.setattr(api, "list_execution_sessions", lambda root, state: [{
        "session-id": f"ses_example_{root.name}",
        "state": "active",
        "created-at": now,
        "updated-at": now,
    }])
    queue = Mock()
    queue.project_queue_depths.side_effect = lambda root: {
        "gpt-auto": {"pending": 1, "running": 1, "active_running": 1, "idle": 0}
    }
    monkeypatch.setattr(api, "get_queue_manager", lambda: queue)
    service_root = tmp_path / "service"
    snapshot = dashboard_snapshot(service_root)
    assert len(snapshot["projects"]) == 1
    project = snapshot["projects"][0]
    assert project["name"] == "AUDiaGentic"
    assert project["project-id"] == project_group_image_id("AUDiaGentic")
    assert project["queues"]["gpt-auto"]["pending"] == 2
    assert project["queues"]["gpt-auto"]["running"] == 2
    assert len(project["requests"]) == len(project["sessions"]) == 2
    assert {(s["worktree"], s["project-id"]) for s in project["sessions"]} == {
        (root.name, project_image_id(root)) for root in roots
    }
    assert {(r["worktree"], r["project-id"]) for r in project["requests"]} == {
        (root.name, project_image_id(root)) for root in roots
    }


def test_logical_avatar_is_allowed_but_checkout_actions_resolve_exact_root(tmp_path, monkeypatch):
    roots = [tmp_path / "main-checkout", tmp_path / "feature-one"]
    for root in roots:
        root.mkdir()
    registry = SimpleNamespace(projects=tuple(SimpleNamespace(project_root=root) for root in roots))
    monkeypatch.setattr(known_projects, "load_known_projects", lambda _path: registry)
    monkeypatch.setattr(project_api, "project_id", lambda _root: ("AUDiaGentic", "settings"))
    app = object.__new__(GatewayServiceApplication)
    app._service_store = SimpleNamespace(root=tmp_path / "service")
    app._application = Mock()
    app._operations = Mock()
    assert app.dashboard_project_image(project_group_image_id("AUDiaGentic")) == b""
    app.close_dashboard_session(project_image_id(roots[1]), "ses_example_000000000001")
    app._application.close_execution_session.assert_called_once_with(
        roots[1], "ses_example_000000000001"
    )


def test_queue_fairness_key_is_logical_but_depths_remain_checkout_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(queue_mod, "project_id", lambda _root: ("AUDiaGentic", "settings"))
    manager = queue_mod.GatewayQueueManager()
    roots = [tmp_path / "main-checkout", tmp_path / "feature-one"]
    for root in roots:
        root.mkdir()
    hold = threading.Event()
    started = threading.Event()

    def runner(root: Path, record: dict):
        started.set()
        hold.wait(timeout=5)
        return store.transition_record(root, record["request-id"], "completed",
                                       updates={"output": "done", "finished-at": now_iso_z()})

    def submit(root: Path):
        record = store.build_record(execution_profile_id="gpt-auto", prompt_body="x")
        store.write_record(root, record)
        manager.enqueue(root, record, {"virtual-capacity": 2, "project-capacity": 1}, runner)
        return record["request-id"]

    try:
        submit(roots[0])
        assert started.wait(timeout=2)
        second = submit(roots[1])
        pending = manager._pending_authority.get(second)
        assert pending is not None and pending.project_key == "AUDiaGentic"
        assert manager.project_queue_depths(roots[0])["gpt-auto"]["running"] == 1
        assert manager.project_queue_depths(roots[1])["gpt-auto"]["pending"] == 1
    finally:
        hold.set()
        manager.shutdown()
