"""Canonical duplicate-ID rekey: only the active record may move."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from audiagentic.components.planning import planning_api, planning_mcp
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _duplicate(root: Path, *, plan: str = "run-hip-autotune") -> tuple[Path, Path]:
    result = planning_api.create_item(
        root,
        {
            "id": "RHA07",
            "plan": plan,
            "title": "Stage advisory lifecycle",
            "description": "Original pending scope preserved across the move.",
            "validation": "Unit and hardware acceptance still pending.",
            "acceptance_criteria": "Prove every stage advisory boundary.",
        },
    )
    source = root / result["path"]
    original = source.read_bytes()
    planning_api.set_state(root, "RHA07", "completed")
    terminal = root / "docs/planning/completed" / plan / "RHA07.md"
    assert terminal.is_file()
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(
        original
    )  # Deliberate corrupt-state fixture, never production code.
    return source, terminal


def test_rekey_only_active_duplicate_preserves_history_and_scope(tmp_path: Path):
    active, completed = _duplicate(tmp_path)
    before = completed.read_bytes()
    with pytest.raises(AudiaGenticError, match="VAL-PLN-036"):
        planning_api.get_item(tmp_path, "RHA07")
    response = planning_api.rekey_duplicate_active_item(
        tmp_path, "run-hip-autotune", "RHA07", "RHA16"
    )
    assert response["old_id"] == "RHA07"
    assert response["id"] == "RHA16"
    assert response["state"] == "pending"
    new = active.with_name("RHA16.md")
    assert new.exists() and not active.exists()
    assert completed.read_bytes() == before
    assert "Original pending scope preserved" in new.read_text()
    assert "Rekeyed active duplicate RHA07 to RHA16" in new.read_text()
    assert planning_api.get_item(tmp_path, "RHA07")["state"] == "completed"
    assert planning_api.get_item(tmp_path, "RHA16")["state"] == "pending"
    assert (
        planning_api.list_items(tmp_path, state="active", plan="run-hip-autotune")[0][
            "id"
        ]
        == "RHA16"
    )


def test_rekey_rejects_target_identity_collision_without_modification(tmp_path: Path):
    active, completed = _duplicate(tmp_path)
    planning_api.create_item(
        tmp_path,
        {"id": "RHA16", "plan": "other-plan", "title": "reserved elsewhere"},
    )
    old = active.read_bytes()
    terminal = completed.read_bytes()
    with pytest.raises(AudiaGenticError, match="VAL-PLN-005"):
        planning_api.rekey_duplicate_active_item(
            tmp_path, "run-hip-autotune", "RHA07", "RHA16"
        )
    assert active.read_bytes() == old and completed.read_bytes() == terminal


def test_rekey_rejects_normal_single_item_and_same_id(tmp_path: Path):
    planning_api.create_item(
        tmp_path,
        {"id": "RHA07", "plan": "run-hip-autotune", "title": "Not duplicated"},
    )
    with pytest.raises(AudiaGenticError, match="VAL-PLN-036"):
        planning_api.rekey_duplicate_active_item(
            tmp_path, "run-hip-autotune", "RHA07", "RHA16"
        )
    with pytest.raises(AudiaGenticError, match="VAL-PLN-036"):
        planning_api.rekey_duplicate_active_item(
            tmp_path, "run-hip-autotune", "RHA07", "RHA07"
        )


def test_rekey_refuses_linked_historical_reviews(tmp_path: Path):
    result = planning_api.create_item(
        tmp_path,
        {
            "id": "RHA07",
            "plan": "run-hip-autotune",
            "title": "Reviewed scope",
            "validation": "Evidence passed.",
            "acceptance_criteria": "Implemented and verified.",
        },
    )
    active = tmp_path / result["path"]
    review = planning_api.create_review(
        tmp_path, {"review-of": "RHA07", "title": "Existing review"}
    )
    planning_api.set_review_state(tmp_path, review["id"], "closed")
    original = active.read_bytes()
    planning_api.set_state(tmp_path, "RHA07", "completed")
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_bytes(original)
    with pytest.raises(AudiaGenticError, match="VAL-PLN-037"):
        planning_api.rekey_duplicate_active_item(
            tmp_path, "run-hip-autotune", "RHA07", "RHA16"
        )
    assert active.exists()
    assert not active.with_name("RHA16.md").exists()


def test_rekey_refuses_corrupt_historical_placement(tmp_path: Path):
    active, completed = _duplicate(tmp_path)
    completed.write_text(
        completed.read_text().replace("state: completed", "state: pending"),
        encoding="utf-8",
    )
    with pytest.raises(Exception):
        planning_api.rekey_duplicate_active_item(
            tmp_path, "run-hip-autotune", "RHA07", "RHA16"
        )
    assert active.exists() and completed.exists()


def test_mcp_rekey_delegates_to_the_one_canonical_api():
    with (
        patch(
            "audiagentic.components.planning.planning_mcp.project_root_from_env",
            return_value=Path("/fake/root"),
        ),
        patch(
            "audiagentic.components.planning.planning_api.rekey_duplicate_active_item",
            return_value={"id": "RHA16", "state": "pending"},
        ) as api,
    ):
        result = planning_mcp.plan_rekey_duplicate_active_item(
            "run-hip-autotune", "RHA07", "RHA16"
        )
    assert result["id"] == "RHA16"
    api.assert_called_once_with(
        Path("/fake/root"), "run-hip-autotune", "RHA07", "RHA16"
    )
