"""Legacy changelog import."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError


def _parse_legacy_changelog(path: Path) -> list[str]:
    if not path.exists():
        raise AudiaGenticError(
            code="RLS-VALIDATION-030",
            kind="validation",
            message="legacy changelog not found",
            details={"path": str(path)},
        )
    entries: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("- "):
            entries.append(line[2:])
    return entries


def _build_change_event(summary: str, index: int) -> dict[str, Any]:
    event_id = f"chg_legacy_{index:04d}"
    return {
        "contract-version": "v1",
        "event-id": event_id,
        "timestamp-utc": "1970-01-01T00:00:00Z",
        "project-id": "legacy-import",
        "source": {
            "kind": "manual-script",
            "provider-id": None,
            "surface": None,
            "session-id": None,
            "job-id": None,
            "packet-id": None,
        },
        "change-class": "release",
        "files": [],
        "diff-stats": {"files-changed": 0, "insertions": 0, "deletions": 0},
        "technical-summary": summary,
        "user-summary-candidate": summary,
        "status": "released",
    }


def import_legacy_history(project_root: Path, changelog_path: Path) -> list[dict[str, Any]]:
    entries = _parse_legacy_changelog(changelog_path)
    events = [_build_change_event(summary, index + 1) for index, summary in enumerate(entries)]
    report_dir = project_root / ".audiagentic" / "runtime" / "ledger" / "import"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "report.json"
    report_payload = {"event-ids": [event["event-id"] for event in events]}
    report_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
    return events
