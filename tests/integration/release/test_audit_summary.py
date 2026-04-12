from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.release.audit import generate_audit_and_checkin
from tests.helpers import sandbox as sandbox_helper

FIXTURES = ROOT / "docs" / "examples" / "fixtures"


def _load_event(event_id: str, technical: str, user: str) -> dict:
    payload = json.loads((FIXTURES / "change-event.valid.json").read_text(encoding="utf-8"))
    payload["event-id"] = event_id
    payload["technical-summary"] = technical
    payload["user-summary-candidate"] = user
    return payload


def _write_ledger(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True))
            handle.write("\n")


def test_audit_and_checkin_generated(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "audit")
    try:
        ledger = sandbox.repo / "docs" / "releases" / "CURRENT_RELEASE_LEDGER.ndjson"
        entries = [
            _load_event("chg_001", "Added thing", "Added thing"),
            _load_event("chg_002", "Fixed bug", "Fixed bug"),
        ]
        _write_ledger(ledger, entries)
        audit_path, checkin_path = generate_audit_and_checkin(sandbox.repo)

        audit = audit_path.read_text(encoding="utf-8")
        checkin = checkin_path.read_text(encoding="utf-8")
        assert "Audit Summary" in audit
        assert "chg_001" in audit
        assert "Check-In Summary" in checkin
        assert "Added thing" in checkin

        audit2, checkin2 = generate_audit_and_checkin(sandbox.repo)
        assert audit2.read_text(encoding="utf-8") == audit
        assert checkin2.read_text(encoding="utf-8") == checkin
    finally:
        sandbox.cleanup()


def test_audit_with_empty_ledger(tmp_path: Path) -> None:
    sandbox = sandbox_helper.create(tmp_path, "audit-empty")
    try:
        audit_path, checkin_path = generate_audit_and_checkin(sandbox.repo)
        assert audit_path.read_text(encoding="utf-8").startswith("# Audit Summary")
        assert checkin_path.read_text(encoding="utf-8").startswith("# Check-In Summary")
    finally:
        sandbox.cleanup()
