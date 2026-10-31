from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.ledger.archive import _archive_current_ledger_locked
from audiagentic.components.ledger.ledger_api import archive_for_release
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
        json.dumps({**_event("old content"), "status": "released", "release-id": "old"}) + "\n", encoding="utf-8"
    )

    with pytest.raises(AudiaGenticError, match="conflicting content"):
        _archive_current_ledger_locked(tmp_path, "rel_conflict")


def test_archive_skips_identical_events_already_released(tmp_path: Path) -> None:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    prior = {**_event("same content"), "status": "released", "release-id": "v0.2.1"}
    current_duplicate = {**_event("same content"), "status": "unreleased"}
    current_new = {**_event("new content"), "event-id": "chg_new"}
    (releases / "LEDGER.ndjson").write_text(json.dumps(prior) + "\n", encoding="utf-8")
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text(
        "\n".join(json.dumps(event) for event in (current_duplicate, current_new)) + "\n",
        encoding="utf-8",
    )

    result = _archive_current_ledger_locked(tmp_path, "v0.3.0")

    archived = [
        json.loads(line)
        for line in (releases / "LEDGER.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    prior_releases = {
        event["release-id"] for event in archived if event["event-id"] == "chg_same"
    }
    new_releases = {
        event["release-id"] for event in archived if event["event-id"] == "chg_new"
    }
    assert result["archived-events"] == 1
    assert prior_releases == {"v0.2.1"}
    assert new_releases == {"v0.3.0"}


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


def test_archive_preserves_legacy_event_ids_with_safe_punctuation(tmp_path: Path) -> None:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    legacy_ids = (
        "chg_20260620_071526_each-ai-provider's-capabilitie_3588",
        "chg_20260620_081436_provider-surface-files-(claude_2732",
        "chg_20260621_012028_lifecycle-unit,-release-integr_2351",
    )
    historical_events = [
        {
            **_event(f"historical event {index}"),
            "event-id": event_id,
            "status": "released",
            "release-id": "rel_previous",
        }
        for index, event_id in enumerate(legacy_ids)
    ]
    (releases / "LEDGER.ndjson").write_text(
        "".join(json.dumps(event) + "\n" for event in historical_events), encoding="utf-8"
    )
    current = {**_event("new event"), "event-id": "chg_new"}
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text(
        json.dumps(current) + "\n", encoding="utf-8"
    )

    _archive_current_ledger_locked(tmp_path, "rel_next")

    archived = [
        json.loads(line)
        for line in (releases / "LEDGER.ndjson").read_text(encoding="utf-8").splitlines()
    ]
    assert set(legacy_ids) <= {event["event-id"] for event in archived}


def test_release_retry_does_not_claim_next_release_events(tmp_path: Path) -> None:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    first = _event("first release")
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text(
        json.dumps(first) + "\n", encoding="utf-8"
    )

    archive_for_release(tmp_path, "rel_first")
    next_event = {**_event("next release"), "event-id": "chg_next"}
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text(
        json.dumps(next_event) + "\n", encoding="utf-8"
    )

    result = archive_for_release(tmp_path, "rel_first")

    assert result["idempotent-retry"] is True
    assert result["released-event-ids"] == ["chg_same"]
    assert json.loads((releases / "CURRENT_RELEASE_LEDGER.ndjson").read_text())["event-id"] == "chg_next"


def test_empty_current_ledger_is_a_noop_not_an_error(tmp_path: Path) -> None:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text("[]\n", encoding="utf-8")

    result = _archive_current_ledger_locked(tmp_path, "v0.9.9")

    assert result["empty"] is True and result["released-event-ids"] == []
    assert not (releases / "LEDGER.ndjson").exists()


def test_empty_retry_after_a_nonempty_archive_reports_the_release_events(tmp_path: Path) -> None:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text(json.dumps(_event("content")) + "\n", encoding="utf-8")
    first = _archive_current_ledger_locked(tmp_path, "v1.0.0")

    retry = _archive_current_ledger_locked(tmp_path, "v1.0.0")
    other = _archive_current_ledger_locked(tmp_path, "v1.0.1")

    assert retry["released-event-ids"] == first["released-event-ids"] == ["chg_same"]
    assert retry["idempotent-retry"] is True and "empty" not in retry
    assert other["empty"] is True


def test_empty_current_ledger_still_rejects_a_corrupt_historical_ledger(tmp_path: Path) -> None:
    releases = tmp_path / "docs" / "releases"
    releases.mkdir(parents=True)
    (releases / "CURRENT_RELEASE_LEDGER.ndjson").write_text("[]\n", encoding="utf-8")
    (releases / "LEDGER.ndjson").write_text("{not json\n", encoding="utf-8")

    with pytest.raises(AudiaGenticError):
        _archive_current_ledger_locked(tmp_path, "v0.9.9")
