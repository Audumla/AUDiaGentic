"""Provider execution dispatch helpers."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

ProviderRunner = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

_ADAPTER_MODULES: dict[str, str] = {
    "aider": "audiagentic.interoperability.providers.aider.adapter",
    "codex": "audiagentic.interoperability.providers.codex.adapter",
    "claude": "audiagentic.interoperability.providers.claude.adapter",
    "gemini": "audiagentic.interoperability.providers.gemini.adapter",
    "goose": "audiagentic.interoperability.providers.goose.adapter",
    "copilot": "audiagentic.interoperability.providers.copilot.adapter",
    "continue": "audiagentic.interoperability.providers.continue_.adapter",
    "cline": "audiagentic.interoperability.providers.cline.adapter",
    "local-openai": "audiagentic.interoperability.providers.local_openai.adapter",
    "qwen": "audiagentic.interoperability.providers.qwen.adapter",
    "opencode": "audiagentic.interoperability.providers.opencode.adapter",
    "openhands": "audiagentic.interoperability.providers.openhands.adapter",
    "roo": "audiagentic.interoperability.providers.roo.adapter",
}


def _load_runner(provider_id: str) -> ProviderRunner | None:
    module_path = _ADAPTER_MODULES.get(provider_id)
    if module_path is None:
        return None
    module = import_module(module_path)
    runner = getattr(module, "run", None)
    if runner is None:
        raise AudiaGenticError(
            code="PRV-VALIDATION-012",
            kind="validation",
            message="provider adapter is missing a run entrypoint",
            details={"provider-id": provider_id, "module": module_path},
        )
    return runner


def execute_provider(
    *,
    provider_id: str,
    packet_ctx: dict[str, Any],
    provider_cfg: dict[str, Any] | None,
) -> dict[str, Any]:
    """Execute a provider adapter through the stable dispatch seam.

    The adapter layer remains intentionally thin. It preserves the normalized
    packet context and adds execution metadata while leaving provider-specific
    behavior inside the provider adapter module.
    """
    provider_cfg = provider_cfg or {}
    runner = _load_runner(provider_id)
    if runner is None:
        return {
            "provider-id": provider_id,
            "status": "stubbed",
            "execution-mode": provider_cfg.get("access-mode", "none"),
            "model": provider_cfg.get("default-model"),
            "output": "stubbed-response",
        }

    result = runner(packet_ctx, provider_cfg)
    if not isinstance(result, dict):
        raise AudiaGenticError(
            code="PRV-VALIDATION-013",
            kind="validation",
            message="provider adapter must return a mapping",
            details={"provider-id": provider_id, "type": type(result).__name__},
        )

    normalized = dict(result)
    normalized.setdefault("provider-id", provider_id)
    normalized.setdefault("execution-mode", provider_cfg.get("access-mode", "none"))
    normalized.setdefault("model", provider_cfg.get("default-model"))
    normalized.setdefault("status", "ok")
    return normalized
