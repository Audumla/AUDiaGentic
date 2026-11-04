"""Current release summary projection (untracked; the tracked release document is written only at finalize)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.ledger.current_events import pending_events
from audiagentic.components.ledger.paths import generated_current_summary_path
from audiagentic.foundation.io import atomic_write_text


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
    output_path = generated_current_summary_path(project_root)
    atomic_write_text(output_path, _render_markdown(pending_events(project_root)))
    return output_path
