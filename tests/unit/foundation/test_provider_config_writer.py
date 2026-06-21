"""Tests for provider config patch/enable/disable helpers.

Provider enablement lives in feature state (features.yaml); providers.yaml holds
only rich runtime config and never carries `enabled`.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from audiagentic.components.optional.providers.services.provider_config import (
    is_provider_enabled,
    load_provider_config,
    patch_provider_config,
    set_provider_enabled,
)
from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import (
    get_implementation_state,
    set_implementation_state,
)


def _providers_yaml(tmp_path: Path) -> Path:
    return tmp_path / ".audiagentic" / "config" / "runtime" / "providers.yaml"


def test_set_provider_enabled_writes_feature_state(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, "claude", enabled=True)
    assert get_implementation_state(tmp_path, COMPONENT_PROVIDERS, "claude").enabled is True
    assert is_provider_enabled(tmp_path, "claude") is True

    set_provider_enabled(tmp_path, "claude", enabled=False)
    assert is_provider_enabled(tmp_path, "claude") is False


def test_set_provider_enabled_does_not_persist_enabled_to_providers_yaml(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "claude", {"access-mode": "cli"})
    set_provider_enabled(tmp_path, "claude", enabled=True)

    saved = yaml.safe_load(_providers_yaml(tmp_path).read_text(encoding="utf-8"))
    assert "enabled" not in saved["providers"]["claude"]


def test_patch_provider_config_strips_enabled(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "gemini", {"enabled": True, "access-mode": "cli"})

    saved = yaml.safe_load(_providers_yaml(tmp_path).read_text(encoding="utf-8"))
    assert "enabled" not in saved["providers"]["gemini"]
    assert saved["providers"]["gemini"]["access-mode"] == "cli"


def test_patch_provider_config_merges_shallow(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "gemini", {"access-mode": "cli"})
    result = patch_provider_config(tmp_path, "gemini", {"default-model": "gemini-2.0"})

    assert result["providers"]["gemini"]["access-mode"] == "cli"
    assert result["providers"]["gemini"]["default-model"] == "gemini-2.0"


def test_patch_provider_config_does_not_affect_other_providers(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "claude", {"access-mode": "cli"})
    patch_provider_config(tmp_path, "codex", {"access-mode": "env"})

    saved = yaml.safe_load(_providers_yaml(tmp_path).read_text(encoding="utf-8"))
    assert saved["providers"]["claude"]["access-mode"] == "cli"
    assert saved["providers"]["codex"]["access-mode"] == "env"


def test_load_provider_config_derives_enabled_from_feature_state(tmp_path: Path) -> None:
    path = _providers_yaml(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "contract-version: v1",
                "providers:",
                "  codex:",
                "    install-mode: external-configured",
                "    access-mode: cli",
                "    auth-ref: env:OPENAI_API_KEY",
            ]
        ),
        encoding="utf-8",
    )
    # No feature state yet → derived enabled is False.
    assert load_provider_config(tmp_path)["providers"]["codex"]["enabled"] is False

    set_implementation_state(tmp_path, COMPONENT_PROVIDERS, "codex", ImplementationState(enabled=True))
    assert load_provider_config(tmp_path)["providers"]["codex"]["enabled"] is True


def test_feature_state_is_authoritative_for_enabled(tmp_path: Path) -> None:
    patch_provider_config(
        tmp_path,
        "codex",
        {
            "install-mode": "external-configured",
            "access-mode": "cli",
            "auth-ref": "env:OPENAI_API_KEY",
        },
    )
    set_implementation_state(tmp_path, COMPONENT_PROVIDERS, "codex", ImplementationState(enabled=False))
    assert load_provider_config(tmp_path)["providers"]["codex"]["enabled"] is False
