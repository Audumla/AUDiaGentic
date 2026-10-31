"""Provider-specific settings are composed into the runtime provider view."""
from __future__ import annotations

import pytest

from audiagentic.components.providers.services.config.provider_config import (
    load_provider_config,
    patch_provider_config,
)


@pytest.fixture(autouse=True)
def _isolated_user_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)


def test_provider_settings_are_loaded_into_runtime_provider_config(tmp_path):
    settings = tmp_path / ".audiagentic" / "settings.yaml"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(
        "schema_version: 1\n"
        "providers:\n"
        "  opencode:\n"
        "    auth-ref: env:OPENCODE_API_KEY\n"
        "    settings:\n"
        "      model: custom-model\n"
        "      mcp:\n"
        "        enabled: true\n",
        encoding="utf-8",
    )

    config = load_provider_config(tmp_path)
    assert config["providers"]["opencode"]["settings"] == {"model": "custom-model", "mcp": {"enabled": True}}
    assert config["providers"]["opencode"]["auth-ref"] == "env:OPENCODE_API_KEY"


def test_unconfigured_providers_are_absent(tmp_path):
    assert load_provider_config(tmp_path)["providers"] == {}


def test_a_provider_with_only_a_policy_has_no_options(tmp_path):
    settings = tmp_path / ".audiagentic" / "settings.yaml"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("schema_version: 1\nproviders:\n  claude:\n    enabled: auto\n", encoding="utf-8")
    entry = load_provider_config(tmp_path)["providers"]["claude"]
    assert "default-model" not in entry and "enabled" in entry
