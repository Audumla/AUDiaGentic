"""Release finalization."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from audiagentic.contracts.errors import AudiaGenticError


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def _write_ndjson(path: Path, entries: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, sort_keys=True))
                handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _checkpoint_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "release" / "checkpoints" / "finalize.json"


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"historical-appended": False, "docs-written": False}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def finalize_release(project_root: Path, release_id: str = "rel_0001") -> dict[str, Any]:
    current_ledger = project_root / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    checkpoint_path = _checkpoint_path(project_root)
    checkpoint = _load_checkpoint(checkpoint_path)
    events = _load_ndjson(current_ledger)
    if not events and checkpoint.get("historical-appended") and checkpoint.get("docs-written"):
        return {
            "contract-version": "v1",
            "status": "success",
            "release-id": release_id,
            "historical-ledger": str(project_root / "docs" / "releases" / "LEDGER.ndjson"),
        }
    if not events:
        raise AudiaGenticError(
            code="RLS-BUSINESS-020",
            kind="business-rule",
            message="no events available for finalization",
            details={"ledger": str(current_ledger)},
        )

    historical_path = project_root / "docs" / "releases" / "LEDGER.ndjson"
    if not checkpoint.get("historical-appended"):
        historical = _load_ndjson(historical_path)
        by_id = {entry["event-id"]: entry for entry in historical}
        for event in events:
            by_id.setdefault(event["event-id"], event)
        merged = [by_id[key] for key in sorted(by_id.keys())]
        _write_ndjson(historical_path, merged)
        checkpoint["historical-appended"] = True

    if not checkpoint.get("docs-written"):
        changelog = project_root / "docs" / "releases" / "CHANGELOG.md"
        release_notes = project_root / "docs" / "releases" / "RELEASE_NOTES.md"
        version_history = project_root / "docs" / "releases" / "VERSION_HISTORY.md"

        change_lines = [f"## {release_id}"]
        for event in sorted(events, key=lambda e: e.get("event-id", "")):
            change_lines.append(f"- {event.get('user-summary-candidate') or event.get('technical-summary')}")
        change_block = "\n".join(change_lines) + "\n"

        existing = changelog.read_text(encoding="utf-8") if changelog.exists() else "# Changelog\n"
        _write_text(changelog, existing.rstrip() + "\n\n" + change_block)
        _write_text(release_notes, "# Release Notes\n\n" + change_block)
        _write_text(version_history, "# Version History\n\n" + change_block)
        checkpoint["docs-written"] = True

    _write_checkpoint(checkpoint_path, checkpoint)

    _write_ndjson(current_ledger, [])
    _write_text(project_root / "docs" / "releases" / "CURRENT_RELEASE.md", "# Current Release\n\n## Changes\n\n")

    return {
        "contract-version": "v1",
        "status": "success",
        "release-id": release_id,
        "historical-ledger": str(historical_path),
    }
