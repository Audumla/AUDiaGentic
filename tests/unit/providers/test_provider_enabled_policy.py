"""CFG06: providers.<id>.enabled is policy; auto means usable here."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers.services.config import provider_config
from audiagentic.components.providers.services.config.provider_config import (
    is_provider_enabled,
    is_provider_usable,
    provider_enabled_policy,
)
from audiagentic.foundation.config.settings import resolve_settings
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    return root


def _settings(root: Path, providers_yaml: str) -> None:
    (root / ".audiagentic").mkdir(exist_ok=True)
    (root / ".audiagentic" / "settings.yaml").write_text(
        f"schema_version: 1\nproviders:\n{providers_yaml}", encoding="utf-8"
    )


def _availability(monkeypatch: pytest.MonkeyPatch, result: tuple[bool | None, str]) -> None:
    import audiagentic.components.providers.providers_api as providers_api

    monkeypatch.setattr(providers_api, "check_provider_availability", lambda root, provider_id: result)


def test_clean_install_uses_a_provider_once_it_is_observed_available(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert provider_enabled_policy(project, "gpt-auto") == "auto"
    _availability(monkeypatch, (True, "CDP answers"))
    assert is_provider_usable(project, "gpt-auto") is True  # no enablement step
    _availability(monkeypatch, (False, "CDP down"))
    assert is_provider_usable(project, "gpt-auto") is False
    _availability(monkeypatch, (None, "no availability check declared"))
    assert is_provider_usable(project, "gpt-auto") is False


def test_enabled_is_policy_or_persisted_state_never_a_probe(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _availability(monkeypatch, (True, "CDP answers"))
    assert is_provider_enabled(project, "gpt-auto") is False  # the footprint follows state, not availability


def test_explicit_policy_overrides_state_and_availability_and_applies_without_restart(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _availability(monkeypatch, (True, "CDP answers"))
    _settings(project, "  gpt-auto: {enabled: false}\n")
    assert is_provider_enabled(project, "gpt-auto") is False
    assert is_provider_usable(project, "gpt-auto") is False
    _settings(project, "  gpt-auto: {enabled: true}\n")
    (project / ".audiagentic" / "settings.yaml").touch()  # the file changed: the cached policy must be re-read
    assert is_provider_enabled(project, "gpt-auto") is True
    assert is_provider_usable(project, "gpt-auto") is True


def test_invalid_policy_is_rejected(project: Path) -> None:
    _settings(project, "  gpt-auto: {enabled: maybe}\n")
    with pytest.raises(AudiaGenticError):
        resolve_settings(project=project)


def test_persisted_state_still_applies_under_auto(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _availability(monkeypatch, (True, "CDP answers"))
    monkeypatch.setattr(
        provider_config, "get_component_state",
        lambda *a, **k: {"implementations": {"gpt-auto": {"enabled": False}}},
    )
    assert is_provider_usable(project, "gpt-auto") is False  # an explicit disable is not overridden by a probe
