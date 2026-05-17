"""Tests for provider config patch/enable/disable helpers."""
from __future__ import annotations

from pathlib import Path

import yaml

from audiagentic.foundation.config.provider_config import (
    patch_provider_config,
    set_provider_enabled,
)


def test_set_provider_enabled_creates_file_if_missing(tmp_path: Path) -> None:
    result = set_provider_enabled(tmp_path, "claude", enabled=True)

    assert result["providers"]["claude"]["enabled"] is True
    path = tmp_path / ".audiagentic" / "config" / "runtime" / "providers.yaml"
    assert path.exists()


def test_set_provider_enabled_false(tmp_path: Path) -> None:
    set_provider_enabled(tmp_path, "claude", enabled=True)
    result = set_provider_enabled(tmp_path, "claude", enabled=False)

    assert result["providers"]["claude"]["enabled"] is False


def test_set_provider_enabled_preserves_other_fields(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "claude", {"access-mode": "cli", "default-model": "claude-sonnet-4-5"})
    result = set_provider_enabled(tmp_path, "claude", enabled=True)

    assert result["providers"]["claude"]["access-mode"] == "cli"
    assert result["providers"]["claude"]["default-model"] == "claude-sonnet-4-5"
    assert result["providers"]["claude"]["enabled"] is True


def test_patch_provider_config_merges_shallow(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "gemini", {"enabled": True})
    result = patch_provider_config(tmp_path, "gemini", {"access-mode": "cli"})

    assert result["providers"]["gemini"]["enabled"] is True
    assert result["providers"]["gemini"]["access-mode"] == "cli"


def test_patch_provider_config_does_not_affect_other_providers(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "claude", {"enabled": True})
    patch_provider_config(tmp_path, "codex", {"enabled": False})

    path = tmp_path / ".audiagentic" / "config" / "runtime" / "providers.yaml"
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert saved["providers"]["claude"]["enabled"] is True
    assert saved["providers"]["codex"]["enabled"] is False


def test_patch_provider_config_written_atomically(tmp_path: Path) -> None:
    patch_provider_config(tmp_path, "pi", {"enabled": True, "access-mode": "cli"})
    path = tmp_path / ".audiagentic" / "config" / "runtime" / "providers.yaml"
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert saved["providers"]["pi"]["enabled"] is True
    assert saved["providers"]["pi"]["access-mode"] == "cli"
