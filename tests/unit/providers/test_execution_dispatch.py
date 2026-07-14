from __future__ import annotations

import pytest

from audiagentic.components.providers.adapters.base_runner import resolve_execution_model
from audiagentic.components.providers.adapters.codex import adapter as codex_adapter
from audiagentic.components.providers.services.execution import execute_provider
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_resolve_execution_model_prefers_gateway_packet_model() -> None:
    assert resolve_execution_model(
        {"model-id": "packet-model"}, {"default-model": "provider-default"}
    ) == "packet-model"


def test_resolve_execution_model_uses_default_for_direct_callers() -> None:
    assert resolve_execution_model({}, {"default-model": "provider-default"}) == "provider-default"


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


def test_execute_provider_rejects_provider_without_execution() -> None:
    """A provider with no adapter module AND no descriptor execution block is
    an error condition — never a fabricated success-shaped 'stubbed' result.
    Declared stubs (execution: {mode: stub}) remain honest stub runners."""
    with pytest.raises(AudiaGenticError) as exc:
        execute_provider(
            provider_id="unknown-provider",
            packet_ctx={"provider-id": "unknown-provider"},
            provider_cfg={"enabled": True, "access-mode": "none", "default-model": "fallback"},
        )
    assert exc.value.code == "VAL-EXEC-002"
