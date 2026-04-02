"""Current release summary regeneration."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


def _load_ledger(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(__import__("json").loads(line))
    return entries


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
    entries = _load_ledger(ledger_path)
    markdown = _render_markdown(entries)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="CURRENT_RELEASE.", suffix=".tmp", dir=output_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(markdown)
        os.replace(tmp_path, output_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return output_path
