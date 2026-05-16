from __future__ import annotations

from pathlib import Path

from audiagentic.interoperability.providers.descriptors import registry as descriptor_registry
from audiagentic.interoperability.providers.status import build_provider_status


def test_provider_status_reports_cli_and_catalog(tmp_path: Path) -> None:
    project_root = tmp_path
    audi_root = project_root / ".audiagentic"
    (audi_root / "config" / "runtime").mkdir(parents=True)
    (audi_root / "config" / "runtime" / "providers.yaml").write_text(
        "\n".join(
            [
                "contract-version: v1",
                "providers:",
                "  codex:",
                "    enabled: true",
                "    install-mode: external-configured",
                "    access-mode: cli",
                "    default-model: gpt-5.4-mini",
                "    model-aliases:",
                "      fast: gpt-5.4-mini",
                "    catalog-refresh:",
                "      source: cli",
                "      max-age-hours: 168",
                "    prompt-surface:",
                "      enabled: true",
                "      tag-syntax: prefix-token-v1",
                "      first-line-policy: first-non-empty-line",
                "      cli-mode: wrapper-normalize",
                "      vscode-mode: extension-normalize",
                "      settings-profile: codex-prompt-tags-v1",
            ]
        ),
        encoding="utf-8",
    )
    runtime_dir = audi_root / "runtime" / "providers" / "codex"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "model-catalog.json").write_text(
        "\n".join(
            [
                "{",
                '  "contract-version": "v1",',
                '  "provider-id": "codex",',
                '  "fetched-at": "2026-03-30T00:00:00Z",',
                '  "source": "cli",',
                '  "models": [',
                "    {",
                '      "model-id": "gpt-5.4-mini",',
                '      "status": "active",',
                '      "supports-structured-output": true,',
                '      "context-window": 200000',
                "    }",
                "  ]",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    payload = build_provider_status(project_root, provider_id="codex", now_fn=lambda: "2026-03-30T00:00:00Z")
    provider = payload["providers"][0]

    assert payload["ok"] is True
    assert provider["provider-id"] == "codex"
    assert provider["access-mode"] == "cli"
    assert provider["installation"]["cli"]["applicable"] is True
    assert provider["installation"]["cli"]["installed"] in {True, False}
    assert provider["cli-installed"] == provider["installation"]["cli"]["installed"]
    assert provider["installation"]["vscode-extension"]["project"] is False
    assert provider["installation"]["vscode-extension"]["installed"] is None
    assert provider["prompt-surface"]["enabled"] is True
    assert provider["prompt-surface"]["supported-modes"] == ["wrapper-normalize", "extension-normalize"]
    assert provider["catalog-present"] is True
    assert provider["catalog-model-count"] == 1
    assert provider["resolved-model"] == "gpt-5.4-mini"


def test_provider_status_reports_vscode_extension_installation(monkeypatch, tmp_path: Path) -> None:
    project_root = tmp_path
    (project_root / ".vscode").mkdir()
    runtime_config = project_root / ".audiagentic" / "config" / "runtime"
    runtime_config.mkdir(parents=True)
    (runtime_config / "providers.yaml").write_text(
        "\n".join(
            [
                "contract-version: v1",
                "providers:",
                "  cline:",
                "    enabled: true",
                "    install-mode: external-configured",
                "    access-mode: cli",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        descriptor_registry,
        "_list_vscode_extensions",
        lambda: ["saoudrizwan.claude-dev"],
    )

    payload = build_provider_status(project_root, provider_id="cline")
    provider = payload["providers"][0]

    assert provider["installation"]["vscode-extension"]["project"] is True
    assert provider["installation"]["vscode-extension"]["applicable"] is True
    assert provider["installation"]["vscode-extension"]["installed"] is True
    assert provider["vscode-extension-installed"] is True
