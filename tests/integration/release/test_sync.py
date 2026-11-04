from __future__ import annotations

import json
import os
import platform
from pathlib import Path

import pytest
from tests.helpers import sandbox as sandbox_helper

from audiagentic.components.ledger.current_events import iter_events
from audiagentic.components.ledger.recorder import record_change_event
from audiagentic.components.ledger.sync import check_current_ledger
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.package import REPO_ROOT

FIXTURES = REPO_ROOT / "docs" / "examples" / "fixtures"


def _load_event(event_id: str) -> dict:
    payload = json.loads((FIXTURES / "change-event.valid.json").read_text(encoding="utf-8"))
    payload["event-id"] = event_id
    return payload


def test_check_counts_recorded_events_and_is_idempotent(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "sync")
    try:
        record_change_event(sandbox.repo, _load_event("chg_001"))
        record_change_event(sandbox.repo, _load_event("chg_002"))

        assert check_current_ledger(sandbox.repo).pending_count == 2
        assert check_current_ledger(sandbox.repo).pending_count == 2
        # Recording never writes the shared baseline.
        assert not (sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson").exists()
    finally:
        sandbox.cleanup()


def test_events_union_the_frozen_baseline_in_order(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "sync-baseline")
    try:
        record_change_event(sandbox.repo, _load_event("chg_010"))
        baseline = sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps({"event-id": "evt_manual_001", "change-class": "docs"}) + "\n", encoding="utf-8")
        before = baseline.read_text(encoding="utf-8")

        assert [event["event-id"] for event in iter_events(sandbox.repo)] == ["evt_manual_001", "chg_010"]
        assert check_current_ledger(sandbox.repo).pending_count == 2
        assert baseline.read_text(encoding="utf-8") == before  # frozen: never rewritten
    finally:
        sandbox.cleanup()


def test_check_replaces_stale_lock(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "sync-stale")
    try:
        record_change_event(sandbox.repo, _load_event("chg_003"))
        lock_path = sandbox.repo / ".audiagentic" / "runtime" / "ledger" / "sync" / "lock.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            (FIXTURES / "ledger-lock.stale.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        assert check_current_ledger(sandbox.repo).warning == "stale-lock-replaced"
    finally:
        sandbox.cleanup()


def test_check_fails_when_lock_active(tmp_path: Path) -> None:
    """When another process holds the lock, the check raises an error."""
    sandbox = sandbox_helper.create(tmp_path, "sync-active")
    try:
        record_change_event(sandbox.repo, _load_event("chg_004"))
        lock_path = sandbox.repo / ".audiagentic" / "runtime" / "ledger" / "sync" / "lock.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        alive_pid = 1 if platform.system() == "Windows" else os.getpid()
        lock_path.write_text(str(alive_pid), encoding="utf-8")
        if platform.system() == "Windows":
            pytest.skip("lock-alive check uses os.kill which sends SIGKILL on Windows")
        with pytest.raises(AudiaGenticError) as raised:
            check_current_ledger(sandbox.repo)
        assert raised.value.kind == "release"
    finally:
        sandbox.cleanup()
