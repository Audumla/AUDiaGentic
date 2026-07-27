"""Tests for ledger_api.get_fragment."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.ledger import ledger_api
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_get_fragment_finds_event(tmp_path: Path):
    event = {
        "event-id": "chg_findme",
        "change-class": "refactor",
        "technical-summary": "find me",
        "user-summary-candidate": "find me",
        "plan-item-ids": ["CC01"],
        "files": ["src/thing.py"],
        "status": "unreleased",
    }
    ledger_api.record_change(tmp_path, event, sync=True)

    result = ledger_api.get_fragment("chg_findme", tmp_path)
    assert result["event-id"] == "chg_findme"
    assert result["change-class"] == "refactor"
    assert result["plan-item-ids"] == ["CC01"]


def test_get_fragment_not_found(tmp_path: Path):
    with pytest.raises(AudiaGenticError, match="CON-LEDGER-001"):
        ledger_api.get_fragment("chg_no_such", tmp_path)
