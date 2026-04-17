from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from audiagentic.knowledge.events import on_planning_state_change

ROOT = Path(__file__).resolve().parents[2]


def _seed_knowledge_project(root: Path) -> None:
    shutil.copytree(
        ROOT / ".audiagentic" / "knowledge",
        root / ".audiagentic" / "knowledge",
        dirs_exist_ok=True,
    )
    shutil.copytree(
        ROOT / ".audiagentic" / "interoperability",
        root / ".audiagentic" / "interoperability",
        dirs_exist_ok=True,
    )
    (root / "docs" / "knowledge" / "data" / "state").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "knowledge" / "data" / "proposals").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "knowledge" / "data" / "archive").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "knowledge" / "data" / "state" / "sync-state.yml").write_text(
        yaml.safe_dump({"manual_stale_pages": []}, sort_keys=False),
        encoding="utf-8",
    )
    (root / "docs" / "knowledge" / "data" / "state" / "event-state.yml").write_text(
        yaml.safe_dump({"sources": {}, "processed_event_ids": []}, sort_keys=False),
        encoding="utf-8",
    )


def _read_sync_state(root: Path) -> dict:
    return yaml.safe_load(
        (root / "docs" / "knowledge" / "data" / "state" / "sync-state.yml").read_text()
    )


def test_task_done_marks_pages_stale_and_generates_proposals(tmp_path: Path, monkeypatch) -> None:
    _seed_knowledge_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    on_planning_state_change(
        "planning.item.state.changed",
        {"id": "task-0001", "old_state": "in_progress", "new_state": "done"},
        {"subject": {"kind": "task", "id": "task-0001"}},
    )

    state = _read_sync_state(tmp_path)
    stale_pages = set(state.get("manual_stale_pages", []))
    assert {"system-planning", "system-knowledge", "guide-using-planning"} <= stale_pages
    proposals = list(
        (tmp_path / "docs" / "knowledge" / "data" / "proposals").glob("*-event-review.yml")
    )
    assert proposals


def test_blocked_marks_pages_stale_without_generating_proposals(
    tmp_path: Path, monkeypatch
) -> None:
    _seed_knowledge_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    on_planning_state_change(
        "planning.item.state.changed",
        {"id": "task-0002", "old_state": "in_progress", "new_state": "blocked"},
        {"subject": {"kind": "task", "id": "task-0002"}},
    )

    state = _read_sync_state(tmp_path)
    stale_pages = set(state.get("manual_stale_pages", []))
    assert {"system-planning", "system-knowledge"} <= stale_pages
    proposals = list(
        (tmp_path / "docs" / "knowledge" / "data" / "proposals").glob("*-event-review.yml")
    )
    assert not proposals


def test_replay_skipped_by_default(tmp_path: Path, monkeypatch) -> None:
    _seed_knowledge_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    on_planning_state_change(
        "planning.item.state.changed",
        {"id": "task-0003", "old_state": "in_progress", "new_state": "done"},
        {"subject": {"kind": "task", "id": "task-0003"}, "is_replay": True},
    )

    state = _read_sync_state(tmp_path)
    assert state.get("manual_stale_pages", []) == []
    proposals = list(
        (tmp_path / "docs" / "knowledge" / "data" / "proposals").glob("*-event-review.yml")
    )
    assert not proposals


def test_replay_opt_in_processes_event(tmp_path: Path, monkeypatch) -> None:
    _seed_knowledge_project(tmp_path)
    config_path = tmp_path / ".audiagentic" / "interoperability" / "config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config.setdefault("runtime", {}).setdefault("replay", {})["dispatch_on_replay"] = True
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    on_planning_state_change(
        "planning.item.state.changed",
        {"id": "task-0004", "old_state": "in_progress", "new_state": "done"},
        {"subject": {"kind": "task", "id": "task-0004"}, "is_replay": True},
    )

    state = _read_sync_state(tmp_path)
    assert "system-planning" in set(state.get("manual_stale_pages", []))
    proposals = list(
        (tmp_path / "docs" / "knowledge" / "data" / "proposals").glob("*-event-review.yml")
    )
    assert proposals
