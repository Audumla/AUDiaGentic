"""Provider-specific settings are composed into the runtime provider view."""
from __future__ import annotations

from audiagentic.components.providers.services.config.provider_config import (
    load_provider_settings,
    load_provider_config,
)
def test_provider_settings_are_loaded_into_runtime_provider_config(tmp_path):
    path = tmp_path / ".audiagentic" / "config" / "providers" / "opencode.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "provider-id: opencode\n"
        "install-mode: toolchain\n"
        "access-mode: none\n"
        "auth-ref: env:OPENCODE_API_KEY\n"
        "settings:\n"
        "  model: custom-model\n"
        "  mcp:\n"
        "    enabled: true\n",
        encoding="utf-8",
    )

    assert load_provider_settings(tmp_path, "opencode") == {
        "provider-id": "opencode",
        "install-mode": "toolchain",
        "access-mode": "none",
        "auth-ref": "env:OPENCODE_API_KEY",
        "settings": {
            "model": "custom-model",
            "mcp": {"enabled": True},
        },
    }
    config = load_provider_config(tmp_path)
    assert config["providers"]["opencode"]["settings"] == {
        "model": "custom-model",
        "mcp": {"enabled": True},
    }


def test_missing_provider_settings_are_empty(tmp_path):
    assert load_provider_settings(tmp_path, "opencode") == {}
