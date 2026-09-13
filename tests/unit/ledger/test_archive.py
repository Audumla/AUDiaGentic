from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.ledger.archive import _archive_current_ledger_locked
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _event(summary: str) -> dict[str, object]:
    return {
        "event-id": "chg_same",
        "change-class": "code-fix",
        "files": ["src/example.py"],
        "technical-summary": summary,
        "user-summary-candidate": summary,
        "status": "unreleased",
    }


def test_archive_rejects_conflicting_historical_identity(tmp_path: Path) -> None:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text(
        json.dumps(_event("new content")) + "\n", encoding="utf-8"
    )
    (releases / "LEDGER.ndjson").write_text(
        json.dumps(_event("old content")) + "\n", encoding="utf-8"
    )

    with pytest.raises(AudiaGenticError, match="conflicting content"):
        _archive_current_ledger_locked(tmp_path, "rel_conflict")


def test_archive_is_idempotent_for_same_release(tmp_path: Path) -> None:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text(
        json.dumps(_event("same content")) + "\n", encoding="utf-8"
    )

    first = _archive_current_ledger_locked(tmp_path, "rel_same")
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text(
        json.dumps({**_event("same content"), "status": "unreleased"}) + "\n",
        encoding="utf-8",
    )
    second = _archive_current_ledger_locked(tmp_path, "rel_same")

    assert first["archived-events"] == second["archived-events"] == 1
    assert len((releases / "LEDGER.ndjson").read_text(encoding="utf-8").splitlines()) == 1
