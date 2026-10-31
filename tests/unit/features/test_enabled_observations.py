"""Implementation enabled is lifecycle state in the observation store; the migration moves old shard flags."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from audiagentic.foundation.features import observations
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.migration import (
    apply_enabled_migration,
    plan_enabled_migration,
    rollback_enabled_migration,
)
from audiagentic.foundation.features.state import (
    SHARD_DIR,
    get_component_state,
    get_implementation_state,
    remove_implementation_state,
    set_component_state,
    set_implementation_state,
)


def _shard(project: Path, component: str, data: dict) -> Path:
    path = project / SHARD_DIR / f"{component}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_observations_carry_time_and_apply_staleness(tmp_path: Path) -> None:
    then = datetime(2026, 1, 1, tzinfo=UTC)
    observations.record_observation(tmp_path, "providers", "k", True, source="t", now=then)
    assert observations.get_observation(tmp_path, "providers", "k") is True
    assert observations.get_observation(
        tmp_path, "providers", "k", max_age=timedelta(hours=1), now=then + timedelta(hours=2)) is None
    assert observations.observed_keys(tmp_path, "providers") == ["k"]
    assert observations.clear_observation(tmp_path, "providers", "k") is True
    assert observations.clear_observation(tmp_path, "providers", "k") is False
    assert not (tmp_path / ".audiagentic" / "settings.yaml").exists()


def test_enabled_is_stored_as_an_observation_not_in_the_shard(tmp_path: Path) -> None:
    set_implementation_state(tmp_path, "providers", "claude", ImplementationState(enabled=True, options={"a": 1}))
    shard = yaml.safe_load((tmp_path / SHARD_DIR / "providers.yaml").read_text())
    assert shard == {"implementations": {"claude": {"options": {"a": 1}}}}
    assert observations.get_observation(tmp_path, "providers", "enabled:claude") is True
    state = get_implementation_state(tmp_path, "providers", "claude")
    assert (state.enabled, state.options) == (True, {"a": 1})
    assert get_component_state(tmp_path, "providers")["implementations"]["claude"]["enabled"] is True


def test_replacing_a_component_clears_enabled_flags_it_no_longer_lists(tmp_path: Path) -> None:
    set_component_state(tmp_path, "agents", {"implementations": {"a": {"enabled": True}, "b": {"enabled": True}}})
    set_component_state(tmp_path, "agents", {"implementations": {"a": {"enabled": False}}})
    assert observations.get_observation(tmp_path, "agents", "enabled:a") is False
    assert observations.get_observation(tmp_path, "agents", "enabled:b") is None


def test_removing_an_implementation_removes_its_flag(tmp_path: Path) -> None:
    set_implementation_state(tmp_path, "providers", "claude", ImplementationState(enabled=True))
    assert remove_implementation_state(tmp_path, "providers", "claude") is True
    assert observations.get_observation(tmp_path, "providers", "enabled:claude") is None


def _legacy(project: Path) -> list[Path]:
    return [
        _shard(project, "providers", {"implementations": {"claude": {"enabled": True, "options": {"x": 1}}}}),
        _shard(project, "coding_lsp", {"implementations": {"pyright": {"enabled": False}}, "features": {"a:b": {"enabled": True}}}),
    ]


def test_migration_moves_flags_and_keeps_everything_else(tmp_path: Path) -> None:
    providers, lsp = _legacy(tmp_path)
    plan = plan_enabled_migration(tmp_path)
    assert plan.flags == {("providers", "claude"): True, ("coding_lsp", "pyright"): False}
    result = apply_enabled_migration(tmp_path)
    assert result["status"] == "applied" and result["flags"] == 2
    assert yaml.safe_load(providers.read_text()) == {"implementations": {"claude": {"options": {"x": 1}}}}
    assert yaml.safe_load(lsp.read_text())["features"] == {"a:b": {"enabled": True}}
    assert observations.get_observation(tmp_path, "providers", "enabled:claude") is True
    assert observations.get_observation(tmp_path, "coding_lsp", "enabled:pyright") is False
    assert plan_enabled_migration(tmp_path).empty
    assert apply_enabled_migration(tmp_path) == {"status": "nothing-to-migrate"}


def test_conflicting_observation_refuses_and_touches_nothing(tmp_path: Path) -> None:
    providers, _ = _legacy(tmp_path)
    before = providers.read_bytes()
    observations.record_observation(tmp_path, "providers", "enabled:claude", False, source="test")
    with pytest.raises(ValueError, match="refused"):
        apply_enabled_migration(tmp_path)
    assert providers.read_bytes() == before


def test_rollback_round_trip(tmp_path: Path) -> None:
    shards = _legacy(tmp_path)
    originals = [p.read_bytes() for p in shards]
    manifest = Path(apply_enabled_migration(tmp_path)["manifest"])
    assert json.loads(manifest.read_text())["status"] == "applied"
    report = rollback_enabled_migration(tmp_path, manifest)
    assert report["kept"] == []
    assert [p.read_bytes() for p in shards] == originals
    assert observations.observed_keys(tmp_path, "providers", "enabled:") == []
    assert rollback_enabled_migration(tmp_path, manifest) == {"restored": [], "kept": []}


def test_rollback_keeps_what_changed_since(tmp_path: Path) -> None:
    providers, lsp = _legacy(tmp_path)
    manifest = Path(apply_enabled_migration(tmp_path)["manifest"])
    set_implementation_state(tmp_path, "providers", "claude", ImplementationState(enabled=False, options={"x": 1}))
    lsp_edit = yaml.safe_load(lsp.read_text())
    lsp_edit["features"]["a:b"]["enabled"] = False
    lsp.write_text(yaml.safe_dump(lsp_edit))
    report = rollback_enabled_migration(tmp_path, manifest)
    assert any("providers.claude" in k for k in report["kept"])
    assert any("coding_lsp.yaml" in k for k in report["kept"])
    assert any("coding_lsp.pyright" in k for k in report["kept"])
    assert observations.get_observation(tmp_path, "coding_lsp", "enabled:pyright") is False


def test_config_migrate_command_previews_applies_and_rolls_back(tmp_path: Path, monkeypatch, capsys) -> None:
    import argparse

    from audiagentic.commands.settings import run_settings_command

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    _legacy(project)

    def run(**kw) -> dict:
        args = argparse.Namespace(config_cmd="migrate", project=project, config_file=None, as_json=True,
                                  apply=False, rollback=None, **kw)
        assert run_settings_command(args) == 0
        return json.loads(capsys.readouterr().out)

    assert run()["applied"] is False and run()["enabled-flags"] == 2
    assert yaml.safe_load((project / SHARD_DIR / "providers.yaml").read_text())["implementations"]["claude"]["enabled"]
    args = argparse.Namespace(config_cmd="migrate", project=project, config_file=None, as_json=True,
                              apply=True, rollback=None)
    assert run_settings_command(args) == 0
    manifest = json.loads(capsys.readouterr().out)["enabled-flags"]["manifest"]
    assert observations.get_observation(project, "providers", "enabled:claude") is True
    args = argparse.Namespace(config_cmd="migrate", project=project, config_file=None, as_json=True,
                              apply=False, rollback=manifest)
    assert run_settings_command(args) == 0
    assert json.loads(capsys.readouterr().out)["kept"] == []
