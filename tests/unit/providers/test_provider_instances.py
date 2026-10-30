"""Provider instances: one descriptor, several configured targets."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.descriptors import get_descriptor
from audiagentic.components.providers.descriptors.target import ProviderTarget, base_provider_id
from audiagentic.components.providers.services.config.provider_config import is_provider_usable
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture(autouse=True)
def _isolated_scopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    (tmp_path / ".git").mkdir()


def _write_settings(project: Path, providers: dict) -> None:
    path = project / ".audiagentic" / "settings.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"schema_version": 1, "providers": providers}), encoding="utf-8")


def test_target_key_round_trips_and_names_the_provider() -> None:
    target = ProviderTarget.parse("gpt-auto@alpha")
    assert (target.provider_id, target.instance, target.key) == ("gpt-auto", "alpha", "gpt-auto@alpha")
    assert ProviderTarget.parse("gpt-auto") == ProviderTarget("gpt-auto")
    assert providers_api.provider_target_key("gpt-auto", "alpha") == "gpt-auto@alpha"
    assert providers_api.provider_target_key("gpt-auto") == "gpt-auto"
    assert base_provider_id("gpt-auto@alpha") == "gpt-auto"


@pytest.mark.parametrize("key", ["gpt-auto@", "gpt-auto@A", "gpt-auto@-x", "gpt-auto@" + "a" * 33])
def test_invalid_instance_name_is_rejected(key: str) -> None:
    with pytest.raises(AudiaGenticError) as caught:
        ProviderTarget.parse(key)
    assert caught.value.code == "VAL-PCFG-005"


def test_descriptor_lookup_uses_the_provider_behind_an_instance() -> None:
    assert get_descriptor("gpt-auto@alpha") is get_descriptor("gpt-auto")
    assert get_descriptor("gpt-auto") is not None


def test_two_instances_resolve_from_one_descriptor(tmp_path: Path) -> None:
    _write_settings(
        tmp_path,
        {"gpt-auto": {"instances": {"alpha": {"project-url": "https://example.test/a"},
                                      "beta": {"project-url": "https://example.test/b"}}}},
    )
    alpha = providers_api.get_provider_runtime_config_state(tmp_path, "gpt-auto@alpha")
    beta = providers_api.get_provider_runtime_config_state(tmp_path, "gpt-auto@beta")
    plain = providers_api.get_provider_runtime_config_state(tmp_path, "gpt-auto")
    assert (alpha["provider-id"], beta["provider-id"], plain["provider-id"]) == (
        "gpt-auto@alpha", "gpt-auto@beta", "gpt-auto")
    assert alpha["config"]["project-url"] == "https://example.test/a"
    assert beta["config"]["project-url"] == "https://example.test/b"
    assert "project-url" not in plain["config"]


def test_overlay_merges_over_the_provider_options(tmp_path: Path) -> None:
    provider_file = tmp_path / ".audiagentic" / "config" / "providers" / "gpt-auto.yaml"
    provider_file.parent.mkdir(parents=True)
    provider_file.write_text(
        yaml.safe_dump({"access-mode": "cli", "auth-ref": "env:EXAMPLE_KEY", "install-mode": "external-configured",
                        "settings": {"timeout": 30, "keep": True}}),
        encoding="utf-8",
    )
    _write_settings(tmp_path, {"gpt-auto": {"instances": {"alpha": {"timeout": 60}}}})
    state = providers_api.get_provider_runtime_config_state(tmp_path, "gpt-auto@alpha")
    assert state["config"]["settings"] == {"timeout": 60, "keep": True}


def test_unknown_instance_lists_the_configured_ones(tmp_path: Path) -> None:
    _write_settings(tmp_path, {"gpt-auto": {"instances": {"alpha": {}}}})
    with pytest.raises(AudiaGenticError) as caught:
        providers_api.get_provider_runtime_config_state(tmp_path, "gpt-auto@gamma")
    assert caught.value.code == "VAL-PCFG-006"
    assert caught.value.details["configured"] == ["alpha"]


def test_enablement_policy_of_the_provider_applies_to_its_instances(tmp_path: Path) -> None:
    _write_settings(tmp_path, {"gpt-auto": {"enabled": False, "instances": {"alpha": {}}}})
    assert is_provider_usable(tmp_path, "gpt-auto@alpha") is False
    _write_settings(tmp_path, {"gpt-auto": {"enabled": True, "instances": {"alpha": {}}}})
    assert is_provider_usable(tmp_path, "gpt-auto@alpha") is True
