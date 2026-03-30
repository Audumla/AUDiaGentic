from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.providers.config import validate_provider_config, validate_prompt_surface


def test_validate_prompt_surface_accepts_supported_cli_mode() -> None:
    issues = validate_prompt_surface(
        "codex",
        {
            "prompt-surface": {
                "enabled": True,
                "tag-syntax": "prefix-token-v1",
                "first-line-policy": "first-non-empty-line",
                "cli-mode": "wrapper-normalize",
                "vscode-mode": "unsupported",
                "settings-profile": "codex-prompt-tags-v1",
            }
        },
    )

    assert issues == []


def test_validate_prompt_surface_rejects_enabled_surface_without_supported_modes() -> None:
    issues = validate_prompt_surface(
        "codex",
        {
            "prompt-surface": {
                "enabled": True,
                "tag-syntax": "prefix-token-v1",
                "first-line-policy": "first-non-empty-line",
                "cli-mode": "unsupported",
                "vscode-mode": "unsupported",
                "settings-profile": "codex-prompt-tags-v1",
            }
        },
    )

    assert issues == ["codex: prompt-surface.enabled requires at least one supported cli-mode or vscode-mode"]


def test_validate_provider_config_surfaces_prompt_surface_semantics() -> None:
    payload = {
        "contract-version": "v1",
        "providers": {
            "codex": {
                "enabled": True,
                "install-mode": "external-configured",
                "access-mode": "cli",
                "prompt-surface": {
                    "enabled": True,
                    "tag-syntax": "prefix-token-v1",
                    "first-line-policy": "first-non-empty-line",
                    "cli-mode": "unsupported",
                    "vscode-mode": "unsupported",
                    "settings-profile": "codex-prompt-tags-v1",
                },
            }
        },
    }

    issues = validate_provider_config(payload)

    assert "codex: prompt-surface.enabled requires at least one supported cli-mode or vscode-mode" in issues
