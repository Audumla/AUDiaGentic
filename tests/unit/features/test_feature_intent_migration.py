"""Feature intent in settings, observations as state, and the shard migration with rollback."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from audiagentic.foundation.features import intent, observations
from audiagentic.foundation.features.migration import (
    apply_shard_migration,
    plan_shard_migration,
    rollback_shard_migration,
)
from audiagentic.foundation.features.state import SHARD_DIR


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    return root


def _shard(project: Path, component: str, data: dict) -> Path:
    path = project / SHARD_DIR / f"{component}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _settings(project: Path) -> dict:
    path = project / ".audiagentic" / "settings.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}


def test_intent_distinguishes_absent_false_and_true(project: Path) -> None:
    assert intent.implementation_enabled(project, "memory", "hindsight") is None
    intent.set_implementation_enabled(project, "memory", "hindsight", False)
    assert intent.implementation_enabled(project, "memory", "hindsight") is False
    intent.set_implementation_enabled(project, "memory", "hindsight", True)
    assert intent.implementation_enabled(project, "memory", "hindsight") is True
    intent.set_implementation_enabled(project, "memory", "hindsight", None)
    assert intent.implementation_enabled(project, "memory", "hindsight") is None


def test_feature_intent_component_and_implementation_level(project: Path) -> None:
    intent.set_feature_enabled(project, "coding_lsp", "language", "python", True)
    intent.set_feature_enabled(project, "coding_lsp", "language", "go", False, implementation="pyright")
    assert intent.feature_enabled(project, "coding_lsp", "language", "python") is True
    assert intent.feature_enabled(project, "coding_lsp", "language", "go", "pyright") is False
    assert intent.feature_enabled(project, "coding_lsp", "language", "go") is None
    assert intent.feature_options(project, "coding_lsp", "language", "python") == {}


def test_invalid_intent_is_refused_by_the_schema(project: Path) -> None:
    with pytest.raises(Exception):
        intent.set_intent(("memory", "implementations", "x", "enabled"), "yes", project_root=project)


def test_observations_carry_time_and_apply_staleness(project: Path) -> None:
    then = datetime(2026, 1, 1, tzinfo=UTC)
    observations.record_observation(project, "providers", "claude.available", True, source="reconcile", now=then)
    assert observations.get_observation(project, "providers", "claude.available") is True
    assert observations.get_observation(
        project, "providers", "claude.available", max_age=timedelta(hours=1), now=then + timedelta(hours=2),
    ) is None
    assert observations.observations_path(project, "providers").parent == project / ".audiagentic/state/observations"
    assert observations.clear_observation(project, "providers", "claude.available") is True
    assert observations.clear_observation(project, "providers", "claude.available") is False
    assert not (project / ".audiagentic" / "settings.yaml").exists()  # never configuration


def _legacy(project: Path) -> None:
    _shard(project, "providers", {"implementations": {"claude": {"enabled": True, "options": {"x": 1}}}})
    _shard(project, "coding_lsp", {
        "features": {"language:python": {"enabled": True}},
        "implementations": {"pyright": {"enabled": False, "features": {"language:go": {"enabled": True}}}},
    })


def test_plan_maps_provider_enablement_to_policy_and_the_rest_to_features(project: Path) -> None:
    _legacy(project)
    plan = plan_shard_migration(project)
    assert plan.patch == {
        "features": {
            "providers": {"implementations": {"claude": {"options": {"x": 1}}}},
            "coding_lsp": {
                "features": {"language:python": {"enabled": True}},
                "implementations": {"pyright": {"enabled": False, "features": {"language:go": {"enabled": True}}}},
            },
        },
    }
    assert plan.observations == {("providers", "claude.enabled"): True}
    assert plan.conflicts == {} and plan.unknown == ()


def test_unknown_legacy_fields_and_conflicts_refuse_the_migration(project: Path) -> None:
    _shard(project, "providers", {"implementations": {"claude": {"enabled": True, "mystery": 1}}, "extra": 2})
    plan = plan_shard_migration(project)
    assert set(plan.unknown) == {"providers.extra", "providers.implementations.claude.mystery"}
    with pytest.raises(ValueError, match="refused"):
        apply_shard_migration(project)
    assert (project / SHARD_DIR / "providers.yaml").exists()  # nothing was touched


def test_conflict_with_existing_project_settings_is_reported(project: Path) -> None:
    (project / ".audiagentic").mkdir(parents=True)
    (project / ".audiagentic" / "settings.yaml").write_text(
        "schema_version: 1\nfeatures:\n  coding_lsp:\n    features:\n      'language:python':\n        enabled: false\n",
        encoding="utf-8")
    _legacy(project)
    plan = plan_shard_migration(project)
    assert plan.conflicts == {("features", "coding_lsp", "features", "language:python", "enabled"): (False, True)}
    with pytest.raises(ValueError):
        apply_shard_migration(project)


def test_conflicting_existing_observation_is_reported(project: Path) -> None:
    observations.record_observation(project, "providers", "claude.enabled", False, source="test")
    _legacy(project)
    assert plan_shard_migration(project).conflicts == {("observation", "providers", "claude.enabled"): (False, True)}


def test_a_provider_policy_in_settings_is_untouched_by_migration(project: Path) -> None:
    (project / ".audiagentic").mkdir(parents=True)
    (project / ".audiagentic" / "settings.yaml").write_text(
        "schema_version: 1\nproviders:\n  claude:\n    enabled: false\n", encoding="utf-8")
    _legacy(project)
    apply_shard_migration(project)
    assert _settings(project)["providers"]["claude"]["enabled"] is False


def test_apply_then_rollback_round_trip(project: Path) -> None:
    _legacy(project)
    sources = [project / SHARD_DIR / "providers.yaml", project / SHARD_DIR / "coding_lsp.yaml"]
    originals = [p.read_bytes() for p in sources]
    result = apply_shard_migration(project)
    assert result["status"] == "applied"
    assert not any(p.exists() for p in sources)
    assert intent.feature_enabled(project, "coding_lsp", "language", "python") is True
    assert "providers" not in _settings(project)  # the policy is the user's, never written by migrate
    assert observations.get_observation(project, "providers", "claude.enabled") is True
    manifest = Path(result["manifest"])
    assert json.loads(manifest.read_text())["status"] == "applied"

    report = rollback_shard_migration(project, manifest)
    assert report["kept"] == []
    assert [p.read_bytes() for p in sources] == originals
    assert intent.feature_enabled(project, "coding_lsp", "language", "python") is None
    assert observations.get_observation(project, "providers", "claude.enabled") is None
    assert rollback_shard_migration(project, manifest) == {"restored": [], "kept": [], "sources": []}


def test_rollback_keeps_values_the_user_changed_after_migration(project: Path) -> None:
    _legacy(project)
    manifest = Path(apply_shard_migration(project)["manifest"])
    intent.set_intent(("coding_lsp", "implementations", "pyright", "enabled"), True, project_root=project)
    report = rollback_shard_migration(project, manifest)
    assert "features.coding_lsp.implementations.pyright.enabled" in report["kept"]
    assert intent.implementation_enabled(project, "coding_lsp", "pyright") is True


def test_nothing_to_migrate_without_shards(project: Path) -> None:
    assert apply_shard_migration(project) == {"status": "nothing-to-migrate"}
