from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.release.current_summary import regenerate_current_release
from tests.helpers import sandbox as sandbox_helper

FIXTURES = ROOT / "docs" / "examples" / "fixtures"


def _load_event(event_id: str, change_class: str, summary: str) -> dict:
    payload = json.loads((FIXTURES / "change-event.valid.json").read_text(encoding="utf-8"))
    payload["event-id"] = event_id
    payload["change-class"] = change_class
    payload["user-summary-candidate"] = summary
    return payload


def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True))
            handle.write("\n")


def test_current_release_summary_deterministic(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "current-release")
    try:
        ledger = sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
        entries = [
            _load_event("chg_002", "feature", "Added feature"),
            _load_event("chg_001", "code-fix", "Fixed bug"),
        ]
        _write_ledger(ledger, entries)

        output = regenerate_current_release(sandbox.repo)
        content = output.read_text(encoding="utf-8")
        assert "# Current Release" in content
        assert "### code-fix" in content
        assert "### feature" in content
        assert "[chg_001] Fixed bug" in content
        assert "[chg_002] Added feature" in content

        content2 = regenerate_current_release(sandbox.repo).read_text(encoding="utf-8")
        assert content2 == content
    finally:
        sandbox.cleanup()


def test_current_release_summary_with_empty_ledger(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "current-release-empty")
    try:
        output = regenerate_current_release(sandbox.repo)
        content = output.read_text(encoding="utf-8")
        assert "# Current Release" in content
    finally:
        sandbox.cleanup()
