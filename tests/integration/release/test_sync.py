from __future__ import annotations

import json
import os
from datetime import datetime, timezone
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.runtime.release.fragments import record_change_event
from audiagentic.runtime.release.sync import sync_current_release_ledger
from tests.helpers import sandbox as sandbox_helper

FIXTURES = ROOT / "docs" / "examples" / "fixtures"


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
        lines = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert [entry["event-id"] for entry in lines] == ["chg_001", "chg_002"]

        # idempotent
        result2 = sync_current_release_ledger(sandbox.repo)
        assert result2.fragment_count == 2
        lines2 = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert lines2 == lines
    finally:
        sandbox.cleanup()


def test_sync_replaces_stale_lock(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "sync-stale")
    try:
        record_change_event(sandbox.repo, _load_event("chg_003"))
        lock_path = sandbox.repo / ".audiagentic" / "runtime" / "ledger" / "sync" / "lock.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text((FIXTURES / "ledger-lock.stale.json").read_text(encoding="utf-8"), encoding="utf-8")
        result = sync_current_release_ledger(sandbox.repo)
        assert result.warning == "stale-lock-replaced"
    finally:
        sandbox.cleanup()


def test_sync_fails_when_lock_active(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "sync-active")
    try:
        record_change_event(sandbox.repo, _load_event("chg_004"))
        lock_path = sandbox.repo / ".audiagentic" / "runtime" / "ledger" / "sync" / "lock.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_payload = {
            "pid": os.getpid(),
            "hostname": "localhost",
            "acquired-at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "command": "sync-current-release-ledger",
        }
        lock_path.write_text(json.dumps(lock_payload, indent=2), encoding="utf-8")
        try:
            sync_current_release_ledger(sandbox.repo)
        except AudiaGenticError as exc:
            assert exc.kind == "business-rule"
        else:
            raise AssertionError("expected lock error")
    finally:
        sandbox.cleanup()
