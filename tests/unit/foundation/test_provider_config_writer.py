"""Tests for provider config patch/enable/disable helpers.

Provider enablement lives in feature state (features.yaml); each provider file
holds only rich runtime config and never carries `enabled`.
"""
from __future__ import annotations

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


def _provider_yaml(tmp_path: Path, provider_id: str) -> Path:
    return tmp_path / ".audiagentic" / "config" / "providers" / f"{provider_id}.yaml"


def test_set_provider_enabled_writes_feature_state(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, "claude", enabled=True)
    assert get_implementation_state(tmp_path, "providers", "claude").enabled is True
    assert is_provider_enabled(tmp_path, "claude") is True

    set_provider_enabled(tmp_path, "claude", enabled=False)
    assert is_provider_enabled(tmp_path, "claude") is False


def test_set_provider_enabled_does_not_persist_enabled_to_providers_yaml(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "claude", {"install-mode": "external-configured", "access-mode": "cli"})
    set_provider_enabled(tmp_path, "claude", enabled=True)

    saved = yaml.safe_load(_provider_yaml(tmp_path, "claude").read_text(encoding="utf-8"))
    assert "enabled" not in saved


def test_patch_provider_config_strips_enabled(tmp_path: Path) -> None:
    patch_provider_config(
        tmp_path,
        "gemini",
        {"enabled": True, "install-mode": "external-configured", "access-mode": "cli"},
    )

    saved = yaml.safe_load(_provider_yaml(tmp_path, "gemini").read_text(encoding="utf-8"))
    assert "enabled" not in saved
    assert saved["access-mode"] == "cli"


def test_patch_provider_config_merges_shallow(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "gemini", {"install-mode": "external-configured", "access-mode": "cli"})
    result = patch_provider_config(tmp_path, "gemini", {"default-model": "gemini-2.0"})

    assert result["providers"]["gemini"]["access-mode"] == "cli"
    assert result["providers"]["gemini"]["default-model"] == "gemini-2.0"


def test_patch_provider_config_does_not_affect_other_providers(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "claude", {"install-mode": "external-configured", "access-mode": "cli"})
    patch_provider_config(
        tmp_path,
        "codex",
        {"install-mode": "external-configured", "access-mode": "env", "auth-ref": "env:OPENAI_API_KEY"},
    )

    claude = yaml.safe_load(_provider_yaml(tmp_path, "claude").read_text(encoding="utf-8"))
    codex = yaml.safe_load(_provider_yaml(tmp_path, "codex").read_text(encoding="utf-8"))
    assert claude["access-mode"] == "cli"
    assert codex["access-mode"] == "env"


def test_load_provider_config_derives_enabled_from_feature_state(tmp_path: Path) -> None:
    path = _provider_yaml(tmp_path, "codex")
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                "install-mode: external-configured",
                "access-mode: cli",
                "auth-ref: env:OPENAI_API_KEY",
            ]
        ),
        encoding="utf-8",
    )
    # No feature state yet → derived enabled is False.
    assert load_provider_config(tmp_path)["providers"]["codex"]["enabled"] is False

    set_implementation_state(tmp_path, "providers", "codex", ImplementationState(enabled=True))
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
    set_implementation_state(tmp_path, "providers", "codex", ImplementationState(enabled=False))
    assert load_provider_config(tmp_path)["providers"]["codex"]["enabled"] is False


# ── GP26: patch_provider_config write-time validation guard ─────────────────


def test_patch_provider_config_validates_gpt_auto_before_persisting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GP26: an invalid gpt-auto project patch must be rejected WITHOUT writing."""
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "audihome"))
    path = _provider_yaml(tmp_path, "gpt-auto")

    with pytest.raises(AudiaGenticError) as exc_info:
        patch_provider_config(
            tmp_path,
            "gpt-auto",
            {
                "install-mode": "external-configured",
                "access-mode": "none",
                "settings": {
                    "contract-version": "v1",
                    "turn": {"response-timeout-seconds": "not-a-number"},
                },
            },
        )

    assert exc_info.value.code == "VAL-GPTAUTO-001"
    assert not path.exists()


def test_patch_provider_config_persists_valid_gpt_auto(tmp_path: Path) -> None:
    path = _provider_yaml(tmp_path, "gpt-auto")

    result = patch_provider_config(
        tmp_path,
        "gpt-auto",
        {
            "install-mode": "external-configured",
            "access-mode": "none",
            "settings": {
                "contract-version": "v1",
                "turn": {"response-timeout-seconds": 42},
            },
        },
    )

    assert result["providers"]["gpt-auto"]["settings"]["turn"]["response-timeout-seconds"] == 42
    assert path.exists()
