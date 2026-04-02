from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.execution.providers.status import build_provider_status


def test_provider_status_reports_cli_and_catalog(tmp_path: Path) -> None:
    project_root = tmp_path
    audi_root = project_root / ".audiagentic"
    audi_root.mkdir()
    (audi_root / "providers.yaml").write_text(
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
    assert provider["prompt-surface"]["enabled"] is True
    assert provider["prompt-surface"]["supported-modes"] == ["wrapper-normalize", "extension-normalize"]
    assert provider["catalog-present"] is True
    assert provider["catalog-model-count"] == 1
    assert provider["resolved-model"] == "gpt-5.4-mini"
