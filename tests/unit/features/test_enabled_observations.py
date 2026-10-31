"""Implementation enabled is lifecycle state in the observation store; options and features are settings."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from audiagentic.foundation.features import observations
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import (
    get_component_state,
    get_implementation_state,
    remove_implementation_state,
    set_component_state,
    set_implementation_state,
)


@pytest.fixture(autouse=True)
def _isolated_user_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)


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


def test_enabled_is_an_observation_and_options_are_user_project_settings(tmp_path: Path) -> None:
    from audiagentic.foundation.config.settings import user_project_settings_path

    set_implementation_state(tmp_path, "providers", "claude", ImplementationState(enabled=True, options={"a": 1}))
    saved = yaml.safe_load(user_project_settings_path(tmp_path).read_text())
    assert saved["features"] == {"providers": {"implementations": {"claude": {"options": {"a": 1}}}}}
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
