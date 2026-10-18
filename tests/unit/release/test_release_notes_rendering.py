from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.release.release_please.finalize import render_release_docs


def test_release_notes_group_ledger_events_by_release_language(tmp_path: Path) -> None:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    events = [
        {"event-id": "chg_b", "release-id": "v1", "change-class": "code-fix",
         "files": ["src/start.py"], "technical-summary": "Fixed startup handling.",
         "user-summary-candidate": "Fixed startup handling.", "status": "released"},
        {"event-id": "chg_a", "release-id": "v1", "change-class": "feature",
         "files": ["src/release.py"], "technical-summary": "Added release summaries.",
         "user-summary-candidate": "Added release summaries.", "status": "released"},
    ]
    (releases / "LEDGER.ndjson").write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )

    render_release_docs(tmp_path, "v1")
    notes = (releases / "RELEASE_NOTES.md").read_text(encoding="utf-8")

    assert "### Features" in notes
    assert "### Fixes" in notes
    assert notes.index("### Features") < notes.index("### Fixes")
    assert "Added release summaries." in notes
    assert "Fixed startup handling." in notes
