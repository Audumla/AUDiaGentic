from __future__ import annotations

import json
import os
import platform
from pathlib import Path

import pytest
from tests.helpers import sandbox as sandbox_helper

from audiagentic.components.ledger.fragments import record_change_event
from audiagentic.components.ledger.sync import sync_current_release_ledger
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.package import REPO_ROOT

FIXTURES = REPO_ROOT / "docs" / "examples" / "fixtures"


def _load_event(event_id: str) -> dict:
    payload = json.loads((FIXTURES / "change-event.valid.json").read_text(encoding="utf-8"))
    payload["event-id"] = event_id
    return payload


def test_sync_merges_fragments_idempotent(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "sync")
    try:
        record_change_event(sandbox.repo, _load_event("chg_001"))
        record_change_event(sandbox.repo, _load_event("chg_002"))

        result = sync_current_release_ledger(sandbox.repo)
        assert result.fragment_count == 2
        ledger = sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
        lines = [
            json.loads(line)
            for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [entry["event-id"] for entry in lines] == ["chg_001", "chg_002"]

        # idempotent
        result2 = sync_current_release_ledger(sandbox.repo)
        # The first sync purges merged fragments; a second sync therefore has
        # no pending fragments and must leave the durable ledger unchanged.
        assert result2.fragment_count == 0
        lines2 = [
            json.loads(line)
            for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert lines2 == lines
    finally:
        sandbox.cleanup()


def test_sync_preserves_existing_ledger_and_appends_fragments(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "sync-rebuild")
    try:
        record_change_event(sandbox.repo, _load_event("chg_010"))
        ledger = sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps({"event-id": "evt_manual_001", "change-class": "docs"}) + "\n",
            encoding="utf-8",
        )

        result = sync_current_release_ledger(sandbox.repo)
        assert result.fragment_count == 1
        lines = [
            json.loads(line)
            for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert [entry["event-id"] for entry in lines] == ["evt_manual_001", "chg_010"]
    finally:
        sandbox.cleanup()


def test_sync_replaces_stale_lock(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "sync-stale")
    try:
        record_change_event(sandbox.repo, _load_event("chg_003"))
        lock_path = sandbox.repo / ".audiagentic" / "runtime" / "ledger" / "sync" / "lock.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            (FIXTURES / "ledger-lock.stale.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        result = sync_current_release_ledger(sandbox.repo)
        assert result.warning == "stale-lock-replaced"
    finally:
        sandbox.cleanup()


def test_sync_fails_when_lock_active(tmp_path: Path) -> None:
    """When another process holds the lock, sync raises an error."""
    sandbox = sandbox_helper.create(tmp_path, "sync-active")
    try:
        record_change_event(sandbox.repo, _load_event("chg_004"))
        lock_path = sandbox.repo / ".audiagentic" / "runtime" / "ledger" / "sync" / "lock.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        # On Windows os.kill() sends a signal rather than checking existence; use
        # pid 1 (always alive on POSIX). On non-Windows we also want an alive pid.
        alive_pid = 1 if platform.system() == "Windows" else os.getpid()
        # StartupLock expects the lock file to contain just the PID as a string
        lock_path.write_text(str(alive_pid), encoding="utf-8")

        # On Windows pid 1 never dies and os.kill() is a signal (kills the process).
        # The guard relies on os.kill returning without error -> alive -> locked.
        if platform.system() == "Windows":
            pytest.skip("lock-alive check uses os.kill which sends SIGKILL on Windows")

        try:
            sync_current_release_ledger(sandbox.repo)
        except AudiaGenticError as exc:
            assert exc.kind == "release"
        else:
            raise AssertionError("expected lock error")
    finally:
        sandbox.cleanup()
