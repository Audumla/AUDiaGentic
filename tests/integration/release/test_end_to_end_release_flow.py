from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from tests.helpers import sandbox as sandbox_helper

from audiagentic.release.audit import generate_audit_and_checkin
from audiagentic.release.current_summary import regenerate_current_release
from audiagentic.release.finalize import finalize_release
from audiagentic.release.fragments import record_change_event
from audiagentic.release.sync import sync_current_release_ledger

FIXTURES = ROOT / "docs" / "examples" / "fixtures"


def _load_event(event_id: str, summary: str) -> dict:
    payload = json.loads((FIXTURES / "change-event.valid.json").read_text(encoding="utf-8"))
    payload["event-id"] = event_id
    payload["user-summary-candidate"] = summary
    return payload


def test_end_to_end_release_flow(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "release-e2e")
    try:
        record_change_event(sandbox.repo, _load_event("chg_001", "Add A"))
        record_change_event(sandbox.repo, _load_event("chg_002", "Fix B"))

        sync_current_release_ledger(sandbox.repo)
        regenerate_current_release(sandbox.repo)
        generate_audit_and_checkin(sandbox.repo)

        current_ledger = sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
        historical = sandbox.repo / "docs" / "releases" / "LEDGER.ndjson"
        historical.write_text(current_ledger.read_text(encoding="utf-8"), encoding="utf-8")

        checkpoint_dir = sandbox.repo / ".audiagentic" / "runtime" / "release" / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = json.loads((FIXTURES / "finalize-checkpoint.partial.json").read_text(encoding="utf-8"))
        (checkpoint_dir / "finalize.json").write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")

        finalize_release(sandbox.repo, release_id="rel_e2e")
        lines = [json.loads(line) for line in historical.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 2

        # rerun finalize should not duplicate
        finalize_release(sandbox.repo, release_id="rel_e2e")
        lines2 = [json.loads(line) for line in historical.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines2) == 2
    finally:
        sandbox.cleanup()
