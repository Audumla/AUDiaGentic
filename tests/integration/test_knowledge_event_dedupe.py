from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from audiagentic.knowledge.config import load_config
from audiagentic.knowledge.event_handlers import process_events
from audiagentic.knowledge.event_scanner import _write_event_proposal, scan_events
from audiagentic.knowledge.event_state import prune_event_state
from audiagentic.knowledge.models import EventRecord

ROOT = Path(__file__).resolve().parents[2]


def _seed_knowledge_project(root: Path) -> None:
    shutil.copytree(
        ROOT / ".audiagentic" / "knowledge",
        root / ".audiagentic" / "knowledge",
        dirs_exist_ok=True,
    )
    (root / ".audiagentic" / "planning" / "events").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "knowledge" / "data" / "state").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "knowledge" / "data" / "proposals").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "knowledge" / "data" / "archive").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "knowledge" / "data" / "state" / "event-state.yml").write_text(
        yaml.safe_dump({"sources": {}, "processed_event_ids": []}, sort_keys=False),
        encoding="utf-8",
    )
    (root / "docs" / "knowledge" / "data" / "state" / "sync-state.yml").write_text(
        yaml.safe_dump({"pages": {}, "manual_stale_pages": []}, sort_keys=False),
        encoding="utf-8",
    )


def test_write_event_proposal_reuses_existing_pending_payload(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    config = load_config(tmp_path)
    event = EventRecord(
        event_id="runtime-planning::planning.item.state.changed::task::task-1::ready::manual",
        adapter_id="planning-state-changes",
        event_name="planning.item.state.changed",
        source_path=".audiagentic/planning/events/events.jsonl",
        status="ready",
        observed_at="2026-04-17T09:00:00+00:00",
        affected_pages=["tool-cli"],
        summary="Planning task task-1 state changed to ready",
        details={"payload": {"id": "task-1", "old_state": "draft", "new_state": "ready"}},
    )

    first = _write_event_proposal(config, "tool-cli", [event], mode="review_only")
    second = _write_event_proposal(config, "tool-cli", [event], mode="review_only")

    assert first == second
    proposals = list(config.proposals_root.glob("*-tool-cli-event-review.yml"))
    assert len(proposals) == 1


def test_scan_events_does_not_rediscover_pruned_old_stream_lines(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    config = load_config(tmp_path)
    config.raw.setdefault("events", {})["max_processed_events"] = 1
    stream = tmp_path / ".audiagentic" / "planning" / "events" / "events.jsonl"
    entries = [
        {
            "event": "planning.item.state.changed",
            "id": "task-1",
            "subject": {"kind": "task", "id": "task-1"},
            "old_state": "in_progress",
            "new_state": "done",
            "metadata": {"triggered_by": "manual"},
        },
        {
            "event": "planning.item.state.changed",
            "id": "task-2",
            "subject": {"kind": "task", "id": "task-2"},
            "old_state": "in_progress",
            "new_state": "verified",
            "metadata": {"triggered_by": "manual"},
        },
    ]
    stream.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n",
        encoding="utf-8",
    )

    first = process_events(config)
    assert len(first["processed_event_ids"]) == 2

    prune_event_state(config, max_events=1)
    rescanned = scan_events(config)

    assert rescanned == []
