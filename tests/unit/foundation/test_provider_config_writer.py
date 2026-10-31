"""Tests for provider config patch/enable/disable helpers.

Provider enablement lives in the observation store; a provider's options live in the project
settings file under ``providers.<id>``. Its install and access modes come from the descriptor.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from audiagentic.components.providers.services.config.provider_config import (
    is_provider_enabled,
    load_provider_config,
    patch_provider_config,
    set_provider_enabled,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import (
    get_implementation_state,
    set_implementation_state,
)


@pytest.fixture(autouse=True)
def _isolated_user_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)


def _saved(tmp_path: Path) -> dict:
    path = tmp_path / ".audiagentic" / "settings.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}


def test_set_provider_enabled_writes_feature_state(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, "claude", enabled=True)
    assert get_implementation_state(tmp_path, "providers", "claude").enabled is True
    assert is_provider_enabled(tmp_path, "claude") is True

    set_provider_enabled(tmp_path, "claude", enabled=False)
    assert is_provider_enabled(tmp_path, "claude") is False


def test_set_provider_enabled_does_not_write_settings(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, "claude", enabled=True)
    assert _saved(tmp_path) == {}


def test_patch_provider_config_strips_enabled_and_descriptor_facts(tmp_path: Path) -> None:
    patch_provider_config(
        tmp_path, "gemini",
        {"enabled": True, "install-mode": "external-configured", "access-mode": "cli", "default-model": "m"},
    )
    assert _saved(tmp_path)["providers"]["gemini"] == {"default-model": "m"}


def test_load_provider_config_derives_modes_from_the_descriptor(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "gemini", {"default-model": "m"})
    entry = load_provider_config(tmp_path)["providers"]["gemini"]
    assert entry["default-model"] == "m"
    assert entry["install-mode"] and entry["access-mode"]


def test_patch_provider_config_merges_with_existing_options(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "gemini", {"timeout-seconds": 30})
    result = patch_provider_config(tmp_path, "gemini", {"default-model": "gemini-2.0"})

    assert result["providers"]["gemini"]["timeout-seconds"] == 30
    assert result["providers"]["gemini"]["default-model"] == "gemini-2.0"


def test_patch_provider_config_does_not_affect_other_providers(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "claude", {"default-model": "a"})
    patch_provider_config(tmp_path, "codex", {"auth-ref": "env:OPENAI_API_KEY"})

    saved = _saved(tmp_path)["providers"]
    assert saved["claude"] == {"default-model": "a"}
    assert saved["codex"] == {"auth-ref": "env:OPENAI_API_KEY"}


def test_load_provider_config_derives_enabled_from_feature_state(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "codex", {"auth-ref": "env:OPENAI_API_KEY"})
    # No feature state yet -> derived enabled is False.
    assert load_provider_config(tmp_path)["providers"]["codex"]["enabled"] is False

    set_implementation_state(tmp_path, "providers", "codex", ImplementationState(enabled=True))
    assert load_provider_config(tmp_path)["providers"]["codex"]["enabled"] is True


def test_feature_state_is_authoritative_for_enabled(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "codex", {"auth-ref": "env:OPENAI_API_KEY"})
    set_implementation_state(tmp_path, "providers", "codex", ImplementationState(enabled=False))
    assert load_provider_config(tmp_path)["providers"]["codex"]["enabled"] is False


# ── GP26: patch_provider_config write-time validation guard ─────────────────


def test_patch_provider_config_validates_gpt_auto_before_persisting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GP26: an invalid gpt-auto project patch must be rejected WITHOUT writing."""
    monkeypatch.setenv("_AUDIAGENTIC_HOME", str(tmp_path / "audihome"))

    with pytest.raises(AudiaGenticError) as exc_info:
        patch_provider_config(
            tmp_path,
            "gpt-auto",
            {"settings": {"contract-version": "v1", "turn": {"response-timeout-seconds": "not-a-number"}}},
        )

    assert exc_info.value.code == "VAL-GPTAUTO-001"
    assert _saved(tmp_path) == {}


def test_patch_provider_config_persists_valid_gpt_auto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from audiagentic.components.providers.adapters.gpt_auto import config as gpt_config

    monkeypatch.setattr(gpt_config, "discover_browser_candidates", lambda: ())

    result = patch_provider_config(
        tmp_path,
        "gpt-auto",
        {"settings": {
            "contract-version": "v1",
            "browser": {"executable": sys.executable},
            "turn": {"response-timeout-seconds": 42},
        }},
    )

    assert result["providers"]["gpt-auto"]["settings"]["turn"]["response-timeout-seconds"] == 42
    assert "gpt-auto" in _saved(tmp_path)["providers"]
