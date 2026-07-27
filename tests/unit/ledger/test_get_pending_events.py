"""Tests for ledger_api.get_pending_events."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.ledger import ledger_api


@pytest.fixture
def seeded(tmp_path: Path) -> list[str]:
    """Seed the ledger with events spanning two plan items and one unrelated."""
    events = [
        {
            "event-id": "chg_001",
            "change-class": "refactor",
            "technical-summary": "tier rename",
            "user-summary-candidate": "tier rename",
            "plan-item-ids": ["PC01"],
            "files": ["src/a.py", "src/b.py"],
            "status": "unreleased",
        },
        {
            "event-id": "chg_002",
            "change-class": "feature",
            "technical-summary": "loader merge",
            "user-summary-candidate": "loader merge",
            "plan-item-ids": ["PC01", "PC02"],
            "files": ["src/c.py"],
            "status": "unreleased",
        },
        {
            "event-id": "chg_003",
            "change-class": "config",
            "technical-summary": "catalogue update",
            "user-summary-candidate": "catalogue update",
            "plan-item-ids": ["PC02"],
            "files": ["src/d.py"],
            "status": "unreleased",
        },
        {
            "event-id": "chg_004",
            "change-class": "docs",
            "technical-summary": "no plan link",
            "user-summary-candidate": "no plan link",
            "plan-item-ids": [],
            "files": ["README.md"],
            "status": "unreleased",
        },
    ]
    for event in events:
        ledger_api.record_change(tmp_path, event, sync=True)
    return [e["event-id"] for e in events]


def test_empty_ledger_plan_items(tmp_path: Path):
    result = ledger_api.get_pending_events(tmp_path, group_by="plan-items")
    assert result == {"groups": [], "ungrouped": []}


def test_plan_items_clustering(seeded: list[str], tmp_path: Path):
    result = ledger_api.get_pending_events(tmp_path, group_by="plan-items")

    # chg_001 (PC01), chg_002 (PC01+PC02), chg_003 (PC02) should cluster
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["event-count"] == 3
    assert sorted(group["files"]) == ["src/a.py", "src/b.py", "src/c.py", "src/d.py"]
    event_ids = [s["event-id"] for s in group["summaries"]]
    assert set(event_ids) == {"chg_001", "chg_002", "chg_003"}

    # chg_004 has no plan linkage — ungrouped
    assert len(result["ungrouped"]) == 1
    assert result["ungrouped"][0]["event-id"] == "chg_004"


def test_files_clustering(tmp_path: Path):
    """Events touching the same file cluster together."""
    events = [
        {
            "event-id": "chg_f01",
            "change-class": "refactor",
            "technical-summary": "base changes",
            "user-summary-candidate": "base changes",
            "plan-item-ids": [],
            "files": ["src/base.py", "src/util.py"],
            "status": "unreleased",
        },
        {
            "event-id": "chg_f02",
            "change-class": "feature",
            "technical-summary": "util changes",
            "user-summary-candidate": "util changes",
            "plan-item-ids": [],
            "files": ["src/util.py", "src/extra.py"],
            "status": "unreleased",
        },
        {
            "event-id": "chg_f03",
            "change-class": "docs",
            "technical-summary": "unique file",
            "user-summary-candidate": "unique file",
            "plan-item-ids": [],
            "files": ["README.md"],
            "status": "unreleased",
        },
    ]
    for event in events:
        ledger_api.record_change(tmp_path, event, sync=True)

    result = ledger_api.get_pending_events(tmp_path, group_by="files")

    # chg_f01 and chg_f02 share util.py → one group
    assert len(result["groups"]) == 1
    group = result["groups"][0]
    assert group["event-count"] == 2
    assert sorted(group["files"]) == ["src/base.py", "src/extra.py", "src/util.py"]

    # chg_f03 has no file overlap — ungrouped
    assert len(result["ungrouped"]) == 1
    assert result["ungrouped"][0]["event-id"] == "chg_f03"


def test_flat_mode(seeded: list[str], tmp_path: Path):
    result = ledger_api.get_pending_events(tmp_path, group_by="flat")
    assert "events" in result
    assert len(result["events"]) == 4
    event_ids = [e["event-id"] for e in result["events"]]
    assert set(event_ids) == {"chg_001", "chg_002", "chg_003", "chg_004"}

    # Each entry has compact fields
    for e in result["events"]:
        assert "event-id" in e
        assert "change-class" in e
        assert "user-summary-candidate" in e
        assert "plan-item-ids" in e
        assert "files" in e


def test_released_events_excluded(tmp_path: Path):
    """Only unreleased events appear in pending results."""
    ledger_api.record_change(
        tmp_path,
        {
            "event-id": "chg_pending",
            "change-class": "feature",
            "technical-summary": "pending event",
            "user-summary-candidate": "pending",
            "plan-item-ids": ["X01"],
            "files": ["src/x.py"],
            "status": "unreleased",
        },
        sync=True,
    )
    ledger_api.record_change(
        tmp_path,
        {
            "event-id": "chg_released",
            "change-class": "feature",
            "technical-summary": "released event",
            "user-summary-candidate": "released",
            "plan-item-ids": ["X01"],
            "files": ["src/y.py"],
            "status": "released",
        },
        sync=True,
    )

    result = ledger_api.get_pending_events(tmp_path, group_by="flat")
    assert len(result["events"]) == 1
    assert result["events"][0]["event-id"] == "chg_pending"
