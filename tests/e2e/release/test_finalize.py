from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.runtime.release.finalize import finalize_release
from tests.helpers import sandbox as sandbox_helper

FIXTURES = ROOT / "docs" / "examples" / "fixtures"


def _load_event(event_id: str, summary: str) -> dict:
    payload = json.loads((FIXTURES / "change-event.valid.json").read_text(encoding="utf-8"))
    payload["event-id"] = event_id
    payload["user-summary-candidate"] = summary
    return payload


def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True))
            handle.write("\n")


def test_finalize_appends_once(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "finalize")
    try:
        current_ledger = sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
        entries = [_load_event("chg_001", "Add A"), _load_event("chg_002", "Fix B")]
        _write_ledger(current_ledger, entries)

        result = finalize_release(sandbox.repo, release_id="rel_001")
        assert result["status"] == "success"

        historical = sandbox.repo / "docs" / "releases" / "LEDGER.ndjson"
        lines = [json.loads(line) for line in historical.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 2

        # idempotent
        result2 = finalize_release(sandbox.repo, release_id="rel_001")
        assert result2["status"] == "success"
        lines2 = [json.loads(line) for line in historical.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines2) == 2

        changelog = sandbox.repo / "docs" / "releases" / "CHANGELOG.md"
        assert "rel_001" in changelog.read_text(encoding="utf-8")
    finally:
        sandbox.cleanup()


def test_finalize_fails_with_empty_ledger(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "finalize-empty")
    try:
        try:
            finalize_release(sandbox.repo, release_id="rel_002")
        except AudiaGenticError as exc:
            assert exc.kind == "business-rule"
        else:
            raise AssertionError("expected business-rule error")
    finally:
        sandbox.cleanup()
