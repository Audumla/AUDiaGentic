"""Audit and check-in summary generation."""
from __future__ import annotations

import json
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
            entries.append(json.loads(line))
    return entries


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


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def generate_audit_and_checkin(project_root: Path) -> tuple[Path, Path]:
    ledger_path = project_root / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
    audit_path = project_root / "docs" / "releases" / "AUDIT_SUMMARY.md"
    checkin_path = project_root / "docs" / "releases" / "CHECKIN.md"

    entries = _load_ledger(ledger_path)
    audit = _render_audit(entries)
    checkin = _render_checkin(entries)

    _atomic_write(audit_path, audit)
    _atomic_write(checkin_path, checkin)
    return audit_path, checkin_path
