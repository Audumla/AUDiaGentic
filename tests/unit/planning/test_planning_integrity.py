"""Cross-record planning integrity and recovery tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.ledger import event_outbox as ledger_outbox
from audiagentic.components.planning import durability, integrity, planning_api
from audiagentic.components.planning import events as planning_events
from audiagentic.components.planning.contracts import PlanningIntegrityError
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _item(root: Path, item_id: str = "TST01") -> Path:
    planning_api.create_item(
        root,
        {
            "id": item_id,
            "plan": "test-plan",
            "title": "Test item",
            "created-by": "test",
        },
    )
    return root / "docs" / "planning" / "active" / "test-plan" / f"{item_id}.md"


def test_created_review_has_one_canonical_parent_link(tmp_path: Path) -> None:
    _item(tmp_path)
    planning_api.create_review(tmp_path, {"id": "RV01", "review-of": "TST01", "title": "Review"})

    assert integrity.validate_repository_integrity(tmp_path) == []
    item = planning_api.get_item(tmp_path, "TST01")
    assert item["reviews"] == "- RV01"


def test_review_metadata_corruption_is_reported_and_mutation_fails_closed(tmp_path: Path) -> None:
    _item(tmp_path)
    planning_api.create_review(tmp_path, {"id": "RV01", "review-of": "TST01", "title": "Review"})
    review_path = (
        tmp_path / "docs" / "planning" / "active" / "test-plan" / "reviews" / "TST01" / "RV01.md"
    )
    original = review_path.read_text(encoding="utf-8")
    review_path.write_text(original.replace("plan: test-plan", "plan: wrong-plan"), encoding="utf-8")

    assert integrity.validate_repository_integrity(tmp_path)
    with pytest.raises(PlanningIntegrityError):
        planning_api.get_review(tmp_path, "RV01")
    with pytest.raises(PlanningIntegrityError):
        planning_api.update_review(tmp_path, "RV01", {"notes": "must not write"})
    assert review_path.read_text(encoding="utf-8") != original


def test_completed_item_evidence_is_part_of_repository_integrity(tmp_path: Path) -> None:
    path = _item(tmp_path)
    text = path.read_text(encoding="utf-8")
    text = text.replace("state: pending", "state: completed")
    text = text.replace("active/test-plan", "completed/test-plan")
    path.unlink()
    completed = tmp_path / "docs" / "planning" / "completed" / "test-plan" / "TST01.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(text, encoding="utf-8")

    errors = integrity.validate_repository_integrity(tmp_path)
    assert any("Validation" in error for error in errors)
    assert any("Acceptance Criteria" in error for error in errors)


def test_completed_parent_cannot_receive_or_reopen_active_review(tmp_path: Path) -> None:
    path = _item(tmp_path)
    text_value = path.read_text(encoding="utf-8")
    text_value = text_value.replace("state: pending", "state: completed")
    path.unlink()
    completed = tmp_path / "docs" / "planning" / "completed" / "test-plan" / "TST01.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    completed.write_text(text_value, encoding="utf-8")

    with pytest.raises(AudiaGenticError, match="cannot receive active reviews"):
        planning_api.create_review(tmp_path, {"id": "RV01", "review-of": "TST01", "title": "Review"})


def test_runtime_roots_reject_ancestor_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = tmp_path / ".audiagentic"
    try:
        marker.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable in this environment")

    with pytest.raises(PlanningIntegrityError):
        durability.journal_root(tmp_path)
    with pytest.raises(AudiaGenticError):
        planning_events._outbox_dir(tmp_path)
    with pytest.raises(AudiaGenticError):
        ledger_outbox.outbox_dir(tmp_path)


def test_ledger_projection_failure_remains_retryable(tmp_path: Path) -> None:
    ledger_outbox.enqueue(tmp_path, "chg_projection", ["MISSING01"])
    planning_events.register()

    assert ledger_outbox.drain(tmp_path) == {"delivered": 0, "failed": 1}
    assert (ledger_outbox.outbox_dir(tmp_path) / "chg_projection.json").exists()


def test_prepared_move_rolls_forward_on_reconciliation(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.md"
    target = tmp_path / "target.md"
    source.write_text("source", encoding="utf-8")
    real_apply = durability._apply_manifest

    def apply_then_crash(root: Path, tx_dir: Path, manifest):
        real_apply(root, tx_dir, manifest)
        raise RuntimeError("simulated process termination")

    monkeypatch.setattr(durability, "_apply_manifest", apply_then_crash)
    with pytest.raises(RuntimeError):
        durability.commit_mutation(
            tmp_path,
            {target: "source"},
            [source],
            operation="test.move",
        )
    assert target.read_text(encoding="utf-8") == "source"
    monkeypatch.setattr(durability, "_apply_manifest", real_apply)
    assert durability.reconcile_pending_mutations(tmp_path) == 1
    assert durability.reconcile_pending_mutations(tmp_path) == 0
    assert target.read_text(encoding="utf-8") == "source"


def test_reconciliation_materializes_journaled_event_after_crash(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.md"
    target = tmp_path / "target.md"
    source.write_text("source", encoding="utf-8")
    intent = planning_events.build_planning_event(
        planning_events.PLANNING_ITEM_UPDATED,
        {"id": "TST01"},
        subject_kind="planning-item",
        subject_id="TST01",
        event_id="event-crash-boundary",
    )
    real_apply = durability._apply_manifest

    def apply_then_crash(root: Path, tx_dir: Path, manifest):
        real_apply(root, tx_dir, manifest)
        raise RuntimeError("simulated process termination")

    monkeypatch.setattr(durability, "_apply_manifest", apply_then_crash)
    with pytest.raises(RuntimeError):
        durability.commit_mutation(
            tmp_path,
            {target: "source"},
            [source],
            operation="test.event-move",
            planning_event=intent,
        )

    assert [path for path in durability.transaction_root(tmp_path).iterdir() if path.is_dir()]
    monkeypatch.setattr(durability, "_apply_manifest", real_apply)
    assert durability.reconcile_pending_mutations(tmp_path) == 1
    outbox = tmp_path / ".audiagentic" / "runtime" / "planning" / "outbox"
    assert (outbox / "event-crash-boundary.json").exists()
    assert durability.reconcile_pending_mutations(tmp_path) == 0
    assert not source.exists()


def test_planning_event_outbox_survives_publish_failure_and_retries(tmp_path: Path, monkeypatch) -> None:
    _item(tmp_path)
    original_get_bus = planning_events.get_bus

    def unavailable_bus():
        raise RuntimeError("event bus unavailable")

    monkeypatch.setattr(planning_events, "get_bus", unavailable_bus)
    planning_api.update_item(tmp_path, "TST01", {"notes": "durable update"})

    outbox = tmp_path / ".audiagentic" / "runtime" / "planning" / "outbox"
    entries = sorted(outbox.glob("*.json"))
    assert len(entries) == 1
    record = entries[0].read_text(encoding="utf-8")
    assert entries[0].stem in record

    monkeypatch.setattr(planning_events, "get_bus", original_get_bus)
    assert planning_events.drain_planning_outbox(tmp_path) == {"delivered": 1, "failed": 0}
    assert not list(outbox.glob("*.json"))
