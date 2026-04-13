from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.interoperability.providers.adapters import codex as codex_adapter
from audiagentic.interoperability.providers.execution import execute_provider


def test_execute_provider_normalizes_adapter_result(monkeypatch) -> None:
    monkeypatch.setattr(
        codex_adapter,
        "run",
        lambda packet_ctx, provider_cfg: {
            "provider-id": packet_ctx["provider-id"],
            "status": "ok",
            "model": provider_cfg.get("default-model"),
            "output": "stubbed-response",
        },
    )
    result = execute_provider(
        provider_id="codex",
        packet_ctx={"provider-id": "codex", "packet-id": "pkt-job-003"},
        provider_cfg={"enabled": True, "access-mode": "cli", "default-model": "gpt-5.4-mini"},
    )

    assert result["provider-id"] == "codex"
    assert result["status"] == "ok"
    assert result["execution-mode"] == "cli"
    assert result["model"] == "gpt-5.4-mini"
    assert result["output"] == "stubbed-response"


def test_execute_provider_handles_unknown_provider_as_stubbed() -> None:
    result = execute_provider(
        provider_id="unknown-provider",
        packet_ctx={"provider-id": "unknown-provider"},
        provider_cfg={"enabled": True, "access-mode": "none", "default-model": "fallback"},
    )

    assert result["provider-id"] == "unknown-provider"
    assert result["status"] == "stubbed"
    assert result["execution-mode"] == "none"
    assert result["model"] == "fallback"
