"""Render release documents from the historical ledger after archive."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.ledger.ledger_api import release_events
from audiagentic.components.ledger.validation import load_persisted_events
from audiagentic.foundation.contracts.errors import make_error
from audiagentic.foundation.io import atomic_write_text

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
    events = load_persisted_events(historical_path, role="historical")
    selected = release_events(events, release_id, released_event_ids)
    labels = {
        "feature": "Features", "code-fix": "Fixes", "refactor": "Improvements",
        "docs": "Documentation", "tests": "Testing", "config": "Configuration",
        "release": "Release", "audit": "Audits", "workflow": "Workflow",
    }
    grouped: dict[str, list[str]] = {}
    for event in selected:
        summary = (event.get("user-summary-candidate") or event.get("technical-summary") or "").strip()
        if summary:
            grouped.setdefault(labels.get(event.get("change-class"), "Changes"), []).append(summary)
    change_lines = [f"## {release_id}", ""]
    for label in sorted(grouped):
        change_lines.append(f"### {label}")
        change_lines.extend(f"- {summary}" for summary in grouped[label])
        change_lines.append("")
    change_block = "\n".join(change_lines).rstrip() + "\n"

    changelog_path = releases / "CHANGELOG.md"
    existing = changelog_path.read_text(encoding="utf-8") if changelog_path.exists() else "# Changelog\n"
    already_rendered = any(
        line.strip() == f"## {release_id}" for line in existing.splitlines()
    )
    if not already_rendered:
        atomic_write_text(changelog_path, existing.rstrip() + "\n\n" + change_block)

    release_notes_path = releases / "RELEASE_NOTES.md"
    atomic_write_text(release_notes_path, f"# Release Notes\n\n{change_block}")

    version_history_path = releases / "VERSION_HISTORY.md"
    existing_vh = version_history_path.read_text(encoding="utf-8") if version_history_path.exists() else "# Version History\n"
    if not any(line.strip() == f"## {release_id}" for line in existing_vh.splitlines()):
        atomic_write_text(version_history_path, existing_vh.rstrip() + "\n\n" + change_block)

    result = {
        "release-id": release_id,
        "changelog": str(changelog_path),
        "release-notes": str(release_notes_path),
        "version-history": str(version_history_path),
    }
    if already_rendered:
        result["skipped"] = "changelog and version history already rendered; release notes refreshed"
    return result
