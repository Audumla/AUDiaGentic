from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.helpers import sandbox as sandbox_helper

from audiagentic.components.release import release_api
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.package import REPO_ROOT

FIXTURES = REPO_ROOT / "docs" / "examples" / "fixtures"

pytestmark = pytest.mark.no_parallel


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

        result = release_api.finalize(sandbox.repo, release_id="rel_001")
        assert result["release-id"] == "rel_001"

        historical = sandbox.repo / "docs" / "releases" / "LEDGER.ndjson"
        lines = [json.loads(line) for line in historical.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 2

        # idempotent
        result2 = release_api.finalize(sandbox.repo, release_id="rel_001")
        assert result2["release-id"] == "rel_001"
        lines2 = [json.loads(line) for line in historical.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines2) == 2

        changelog = sandbox.repo / "docs" / "releases" / "CHANGELOG.md"
        assert "rel_001" in changelog.read_text(encoding="utf-8")
    finally:
        sandbox.cleanup()


def test_finalize_fails_when_the_current_ledger_file_is_missing(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "finalize-empty")
    try:
        try:
            release_api.finalize(sandbox.repo, release_id="rel_002")
        except AudiaGenticError as exc:
            assert exc.kind == "release"
        else:
            raise AssertionError("expected business-rule error")
    finally:
        sandbox.cleanup()


def test_finalize_with_no_events_keeps_the_release_please_notes(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "finalize-empty")
    try:
        releases = sandbox.repo / "docs" / "releases"
        _write_ledger(releases / "CURRENT_RELEASE_LEDGER.ndjson", [])
        notes = releases / "RELEASE_NOTES.md"
        notes.write_text("previous release notes\n", encoding="utf-8")

        result = release_api.finalize(sandbox.repo, release_id="rel_empty")

        assert result["notes-source"] == "release-please" and result["empty"] is True
        assert notes.read_text(encoding="utf-8") == "previous release notes\n"
        assert "rel_empty" not in (releases / "VERSION_HISTORY.md").read_text(encoding="utf-8") if (releases / "VERSION_HISTORY.md").exists() else True
    finally:
        sandbox.cleanup()


def test_finalize_with_events_reports_events_as_the_notes_source(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "finalize-events")
    try:
        _write_ledger(sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson", [_load_event("chg_e1", "Add A")])
        assert release_api.finalize(sandbox.repo, release_id="rel_events")["notes-source"] == "events"
    finally:
        sandbox.cleanup()
