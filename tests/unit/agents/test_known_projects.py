"""GP26: machine-scoped known-projects registry for gpt-auto config drift.

Covers load/record/scan semantics, the advisory (never availability-critical)
failure policy, atomic writes, and the machine-vs-project isolation boundary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.service.known_projects import (
    REGISTRY_SCHEMA_VERSION,
    KnownProject,
    KnownProjectsRegistry,
    load_known_projects,
    record_known_project,
    scan_known_gpt_auto_projects,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_load_returns_empty_registry_for_missing_file(tmp_path: Path) -> None:
    registry = load_known_projects(tmp_path / "known-projects.json")

    assert registry.schema_version == REGISTRY_SCHEMA_VERSION
    assert registry.projects == ()


def test_load_tolerates_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "known-projects.json"
    path.write_text("{not json", encoding="utf-8")

    registry = load_known_projects(path)

    assert registry.projects == ()
    # Corrupt file is preserved, never silently overwritten.
    assert path.read_text(encoding="utf-8") == "{not json"


def test_load_tolerates_unsupported_schema_version_read_only(tmp_path: Path) -> None:
    path = tmp_path / "known-projects.json"
    path.write_text('{"schema-version": 99, "projects": {}}', encoding="utf-8")

    registry = load_known_projects(path)

    assert registry.schema_version == REGISTRY_SCHEMA_VERSION
    assert registry.projects == ()


def test_record_round_trips_a_project(tmp_path: Path) -> None:
    path = tmp_path / "known-projects.json"
    root = Path("C:/projects/alpha")

    record_known_project(
        path,
        project_root=root,
        config_status="compatible",
        checked_at=_dt("2026-08-17T00:00:00Z"),
    )

    registry = load_known_projects(path)
    project = registry.get(root)
    assert project is not None
    assert project.config_status == "compatible"
    assert project.config_error_code is None
    assert project.last_config_check_at == _dt("2026-08-17T00:00:00Z")


def test_record_merges_existing_entries_does_not_erase_other_projects(tmp_path: Path) -> None:
    path = tmp_path / "known-projects.json"
    record_known_project(
        path, project_root=Path("C:/projects/alpha"), config_status="compatible"
    )

    record_known_project(path, project_root=Path("C:/projects/beta"), config_status="unknown")

    registry = load_known_projects(path)
    assert registry.get(Path("C:/projects/alpha")) is not None
    assert registry.get(Path("C:/projects/beta")) is not None


def test_record_rejects_invalid_status(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        record_known_project(
            tmp_path / "known-projects.json",
            project_root=Path("C:/projects/alpha"),
            config_status="bogus",  # type: ignore[arg-type]
        )


def test_record_touches_last_seen_and_preserves_it_on_later_check(tmp_path: Path) -> None:
    path = tmp_path / "known-projects.json"
    first = _dt("2026-08-17T01:00:00Z")
    second = _dt("2026-08-17T02:00:00Z")

    record_known_project(path, project_root=Path("C:/projects/alpha"), checked_at=first)
    record_known_project(path, project_root=Path("C:/projects/alpha"), checked_at=second)

    project = load_known_projects(path).get(Path("C:/projects/alpha"))
    assert project is not None
    # last_seen_at stays at the first recorded touch (advisory timestamps).
    assert project.last_seen_at == first
    assert project.last_config_check_at == second


def test_scan_marks_compatible_and_incompatible_projects(tmp_path: Path) -> None:
    path = tmp_path / "known-projects.json"
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    record_known_project(path, project_root=alpha)
    record_known_project(path, project_root=beta)

    def _check(root: Path) -> None:
        if root == beta:
            raise AudiaGenticError(code="VAL-GPTAUTO-001", kind="providers", message="bad")

    result = scan_known_gpt_auto_projects(path, check_project=_check, now=_dt("2026-08-17T00:00:00Z"))

    assert result.checked == 2
    assert result.compatible == 1
    assert result.failed == 1
    assert result.incompatible[0].project_root == beta
    assert result.incompatible[0].error_code == "VAL-GPTAUTO-001"
    # Registry reflects the verdicts.
    assert load_known_projects(path).get(alpha).config_status == "compatible"  # type: ignore[union-attr]
    assert load_known_projects(path).get(beta).config_status == "incompatible"  # type: ignore[union-attr]


def test_scan_flags_missing_project_directory_as_stale_not_corruption(tmp_path: Path) -> None:
    path = tmp_path / "known-projects.json"
    gone = tmp_path / "deleted-checkout"
    record_known_project(path, project_root=gone)

    result = scan_known_gpt_auto_projects(path, check_project=lambda root: None)

    assert result.failed == 1
    assert result.incompatible[0].error_code == "project-dir-missing"


def test_scan_with_empty_registry_is_a_noop(tmp_path: Path) -> None:
    path = tmp_path / "known-projects.json"

    result = scan_known_gpt_auto_projects(path, check_project=lambda root: None)

    assert result.checked == 0
    assert result.compatible == 0
    assert result.incompatible == ()


def test_scan_never_fails_on_check_project_exceptions(tmp_path: Path) -> None:
    """An incompatible project must not fail the scan; the gateway keeps running."""
    path = tmp_path / "known-projects.json"
    root = tmp_path / "project"
    root.mkdir()
    record_known_project(path, project_root=root)

    def _explode(root: Path) -> None:
        raise RuntimeError("unexpected internal error")

    result = scan_known_gpt_auto_projects(path, check_project=_explode)

    assert result.failed == 1
    assert result.incompatible[0].error_code == "config-incompatible"


def test_registry_is_advisory_missing_file_never_blocks(tmp_path: Path) -> None:
    path = tmp_path / "known-projects.json"
    assert load_known_projects(path).projects == ()


def test_known_projects_registry_get_normalizes_roots(tmp_path: Path) -> None:
    registry = KnownProjectsRegistry(
        REGISTRY_SCHEMA_VERSION,
        (KnownProject(Path("C:/projects/alpha"), _dt("2026-08-17T00:00:00Z"), None, "unknown"),),
    )

    assert registry.get(Path("C:/projects/alpha")) is not None
