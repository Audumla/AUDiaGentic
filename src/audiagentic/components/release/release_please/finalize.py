"""Render release documents from the historical ledger after archive."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.io import atomic_write_text, load_ndjson

_RELEASES_DIR = ("docs", "releases")


def render_release_docs(
    project_root: Path,
    release_id: str,
    released_event_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Render CHANGELOG.md, RELEASE_NOTES.md, VERSION_HISTORY.md from LEDGER.ndjson."""
    releases = project_root.joinpath(*_RELEASES_DIR)
    historical_path = releases / "LEDGER.ndjson"
    if not historical_path.exists():
        raise make_error(
            prefix="VAL", component="release", number=3,
            kind="release",
            message="LEDGER.ndjson not found — ledger may not have been archived",
            details={"path": str(historical_path)},
        )
    events = load_ndjson(historical_path)

    if released_event_ids:
        id_set = set(released_event_ids)
        release_events = [e for e in events if e.get("event-id") in id_set]
    else:
        release_events = [e for e in events if e.get("release-id") == release_id]

    change_lines = [f"## {release_id}"]
    for event in sorted(release_events, key=lambda e: e.get("event-id", "")):
        summary = event.get("user-summary-candidate") or event.get("technical-summary")
        if summary:
            change_lines.append(f"- {summary}")
        else:
            change_lines.append("- (no summary)")
    change_block = "\n".join(change_lines) + "\n"

    changelog_path = releases / "CHANGELOG.md"
    existing = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else "# Changelog\n"
    if f"## {release_id}" in existing:
        return {
            "release-id": release_id,
            "changelog": str(changelog_path),
            "release-notes": str(releases / "RELEASE_NOTES.md"),
            "version-history": str(releases / "VERSION_HISTORY.md"),
            "skipped": "already rendered",
        }
    atomic_write_text(changelog_path, existing.rstrip() + "\n\n" + change_block)

    release_notes_path = releases / "RELEASE_NOTES.md"
    atomic_write_text(release_notes_path, f"# Release Notes\n\n{change_block}")

    version_history_path = releases / "VERSION_HISTORY.md"
    existing_vh = version_history_path.read_text(encoding="utf-8") if version_history_path.exists() else "# Version History\n"
    atomic_write_text(version_history_path, existing_vh.rstrip() + "\n\n" + change_block)

    return {
        "release-id": release_id,
        "changelog": str(changelog_path),
        "release-notes": str(release_notes_path),
        "version-history": str(version_history_path),
    }
