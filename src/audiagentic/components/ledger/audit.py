"""Audit and check-in summary generation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.ledger.paths import (
    audit_summary_md_path,
    checkin_md_path,
    current_ledger_path,
)
from audiagentic.foundation.io import atomic_write_text, load_ndjson


def _render_audit(entries: list[dict[str, Any]]) -> str:
    lines = ["# Audit Summary", "", f"Total events: {len(entries)}", ""]
    for entry in sorted(entries, key=lambda e: e.get("event-id", "")):
        lines.append(f"- {entry.get('event-id', '')}: {entry.get('technical-summary', '')}")
    return "\n".join(lines).strip() + "\n"


def _render_checkin(entries: list[dict[str, Any]]) -> str:
    lines = ["# Check-In Summary", "", f"Total changes: {len(entries)}", ""]
    for entry in sorted(entries, key=lambda e: e.get("event-id", "")):
        summary = entry.get("user-summary-candidate") or entry.get("technical-summary") or ""
        lines.append(f"- {summary}")
    return "\n".join(lines).strip() + "\n"


def generate_audit_and_checkin(project_root: Path) -> tuple[Path, Path]:
    ledger_path = current_ledger_path(project_root)
    audit_path = audit_summary_md_path(project_root)
    checkin_path = checkin_md_path(project_root)
    entries = load_ndjson(ledger_path)
    atomic_write_text(audit_path, _render_audit(entries))
    atomic_write_text(checkin_path, _render_checkin(entries))
    return audit_path, checkin_path
