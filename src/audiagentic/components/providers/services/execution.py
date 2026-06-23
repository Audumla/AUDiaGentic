"""Provider execution dispatch helpers."""

from __future__ import annotations

import importlib.util
import keyword
from collections.abc import Callable
from importlib import import_module
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

ProviderRunner = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

_ADAPTER_BASE = "audiagentic.components.providers.adapters"


def _adapter_module_path(provider_id: str) -> str | None:
    name = provider_id.replace("-", "_")
    if keyword.iskeyword(name):
        name = name + "_"
    module_path = f"{_ADAPTER_BASE}.{name}.adapter"
    try:
        return module_path if importlib.util.find_spec(module_path) else None
    except (ModuleNotFoundError, AttributeError):
        return None


def _load_runner(provider_id: str) -> ProviderRunner | None:
    module_path = _adapter_module_path(provider_id)
    if module_path is None:
        return None
    module = import_module(module_path)
    runner = getattr(module, "run", None)
    if runner is None:
        raise AudiaGenticError(
            code="INT-EXEC-001",
            kind="providers",
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
            code="INT-EXEC-002",
            kind="providers",
            message="provider adapter must return a mapping",
            details={"provider-id": provider_id, "type": type(result).__name__},
        )

    normalized = dict(result)
    normalized.setdefault("provider-id", provider_id)
    normalized.setdefault("execution-mode", provider_cfg.get("access-mode", "none"))
    normalized.setdefault("model", provider_cfg.get("default-model"))
    normalized.setdefault("status", "ok")
    return normalized
