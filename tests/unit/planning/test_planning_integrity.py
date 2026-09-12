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

    with pytest.raises(AudiaGenticError):
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


def test_manifestless_staging_is_discarded_on_reconciliation(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target.md"
    real_durable_json = durability._durable_json

    def crash_before_manifest(path: Path, value) -> None:
        if path.name == "manifest.json":
            raise RuntimeError("simulated pre-manifest termination")
        real_durable_json(path, value)

    monkeypatch.setattr(durability, "_durable_json", crash_before_manifest)
    with pytest.raises(RuntimeError, match="pre-manifest"):
        durability.commit_mutation(
            tmp_path,
            {target: "payload"},
            operation="test.pre-manifest",
        )

    assert list(durability.transaction_root(tmp_path).glob(".staging-*/write-*.payload"))
    monkeypatch.setattr(durability, "_durable_json", real_durable_json)
    assert durability.reconcile_pending_mutations(tmp_path) == 0
    assert not list(durability.transaction_root(tmp_path).glob(".staging-*"))
    assert not target.exists()


def test_ledger_projection_intent_precedes_fragment_and_waits_for_fragment(tmp_path: Path, monkeypatch) -> None:
    from audiagentic.components.ledger import fragments

    real_write = fragments.atomic_write_text

    def crash_fragment_write(*args, **kwargs):
        raise RuntimeError("simulated fragment termination")

    monkeypatch.setattr(fragments, "atomic_write_text", crash_fragment_write)
    with pytest.raises(RuntimeError, match="fragment termination"):
        fragments.record_change_event(
            tmp_path,
            {
                "change-class": "audit",
                "files": ["tests/unit/planning/test_planning_integrity.py"],
                "technical-summary": "test",
                "user-summary-candidate": "test",
                "status": "unreleased",
                "plan-item-ids": ["TST01"],
            },
        )
    assert list(ledger_outbox.outbox_dir(tmp_path).glob("*.json"))
    assert ledger_outbox.drain(tmp_path) == {"delivered": 0, "failed": 1}
    monkeypatch.setattr(fragments, "atomic_write_text", real_write)


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


def test_planning_event_outbox_retains_subscriber_failure(tmp_path: Path, monkeypatch) -> None:
    planning_events.enqueue_planning_event(
        tmp_path,
        planning_events.PLANNING_ITEM_UPDATED,
        {"id": "TST01"},
        metadata={"subject": {"kind": "planning-item", "id": "TST01"}},
        event_id="event-subscriber-failure",
    )
    outbox = tmp_path / ".audiagentic" / "runtime" / "planning" / "outbox"
    original_get_bus = planning_events.get_bus

    class FailingBus:
        def publish(self, *args, **kwargs):
            raise RuntimeError("subscriber failed")

    monkeypatch.setattr(planning_events, "get_bus", lambda: FailingBus())
    assert planning_events.drain_planning_outbox(tmp_path) == {"delivered": 0, "failed": 1}
    assert list(outbox.glob("*.json"))
    monkeypatch.setattr(planning_events, "get_bus", original_get_bus)


def test_integrity_rejects_frontmatter_record_with_malformed_filename(tmp_path: Path) -> None:
    _item(tmp_path)
    source = tmp_path / "docs" / "planning" / "active" / "test-plan" / "TST01.md"
    malformed = source.with_name("bad!.md")
    malformed.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    source.unlink()
    errors = integrity.validate_repository_integrity(tmp_path)
    assert errors
    assert "bad!.md" in errors[0]


def test_completed_parent_cannot_reopen_closed_review(tmp_path: Path) -> None:
    _item(tmp_path)
    planning_api.create_review(tmp_path, {"id": "RV01", "review-of": "TST01", "title": "Review"})
    planning_api.set_review_state(tmp_path, "RV01", "closed")
    item_path = tmp_path / "docs" / "planning" / "active" / "test-plan" / "TST01.md"
    completed = tmp_path / "docs" / "planning" / "completed" / "test-plan" / "TST01.md"
    completed.parent.mkdir(parents=True, exist_ok=True)
    item_text = item_path.read_text(encoding="utf-8").replace("state: pending", "state: completed")
    item_path.unlink()
    completed.write_text(item_text, encoding="utf-8")
    with pytest.raises(AudiaGenticError, match="cannot have active reviews"):
        planning_api.set_review_state(tmp_path, "RV01", "considered")
