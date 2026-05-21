"""Current release summary regeneration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_text, load_ndjson


def _render_markdown(entries: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        change_class = entry.get("change-class", "other")
        grouped.setdefault(change_class, []).append(entry)

    lines = ["# Current Release", "", "## Changes", ""]
    for change_class in sorted(grouped.keys()):
        lines.append(f"### {change_class}")
        for entry in sorted(grouped[change_class], key=lambda e: e.get("event-id", "")):
            summary = entry.get("user-summary-candidate") or entry.get("technical-summary") or ""
            event_id = entry.get("event-id", "")
            lines.append(f"- [{event_id}] {summary}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def regenerate_current_release(project_root: Path) -> Path:
    ledger_path = project_root / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    output_path = project_root / "docs" / "releases" / "CURRENT_RELEASE.md"
    entries = load_ndjson(ledger_path)
    atomic_write_text(output_path, _render_markdown(entries))
    return output_path
