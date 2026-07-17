"""Provider execution dispatch helpers."""

from __future__ import annotations

import importlib.util
import keyword
from collections.abc import Callable
from importlib import import_module
from typing import Any

from audiagentic.components.providers.adapters.base_runner import resolve_execution_model
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


def _descriptor_runner(provider_id: str) -> ProviderRunner | None:
    """Build a runner from the provider descriptor's execution: block (AR12)."""
    from audiagentic.components.providers.adapters.base_runner import (
        make_runner_from_execution,
    )
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    descriptor = all_descriptors().get(provider_id)
    execution = getattr(descriptor, "execution", None) if descriptor else None
    if not execution:
        return None
    return make_runner_from_execution(provider_id, execution)


def _load_runner(provider_id: str) -> ProviderRunner | None:
    module_path = _adapter_module_path(provider_id)
    if module_path is None:
        return _descriptor_runner(provider_id)
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


def load_acp_launch_builder(provider_id: str) -> Callable[..., Any] | None:
    """Return the provider's ACP launch builder if it supports live sessions.

    Convention (plan agent-sessions AS04): an adapter package that supports
    live ACP sessions exposes ``build_acp_launch(project_root, *, model_id)``
    in its ``acp`` submodule (opencode already does). Returns None when the
    provider has no live-session support — the caller decides how to fail.
    This is the one allowed provider hook for the session dispatch path,
    mirroring the ``run`` entrypoint convention for one-shot execution.
    """
    name = provider_id.replace("-", "_")
    if keyword.iskeyword(name):
        name = name + "_"
    module_path = f"{_ADAPTER_BASE}.{name}.acp"
    try:
        if not importlib.util.find_spec(module_path):
            return None
    except (ModuleNotFoundError, AttributeError):
        return None
    module = import_module(module_path)
    return getattr(module, "build_acp_launch", None)


_EXECUTION_MODE_BY_DECLARATION: dict[str, str] = {
    "cli": "descriptor",
    "stub": "stub",
    "ok-stub": "stub",
    "unsupported": "unsupported",
}


def describe_execution_support(provider_id: str) -> dict[str, Any]:
    """Report execution support without importing or running adapter modules.

    Modes (MO11 step 1): ``adapter`` (hand-written adapter module exists —
    detected via find_spec, no import), ``descriptor`` (declarative
    ``execution: {mode: cli}`` runner), ``stub``, ``unsupported``, ``none``.
    Stable provider-service API consumed by describe_provider and recipes.
    """
    module_path = _adapter_module_path(provider_id)
    if module_path is not None:
        return {"mode": "adapter", "module": module_path}

    from audiagentic.components.providers.descriptors.registry import all_descriptors

    descriptor = all_descriptors().get(provider_id)
    execution = getattr(descriptor, "execution", None) if descriptor else None
    if not execution:
        return {"mode": "none"}
    declared = execution.get("mode", "")
    mode = _EXECUTION_MODE_BY_DECLARATION.get(declared, "none")
    result: dict[str, Any] = {"mode": mode, "declared": declared}
    if execution.get("message"):
        result["message"] = execution["message"]
    return result


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
    from audiagentic.components.providers.services.launch_env import launch_env_overlay

    provider_cfg = provider_cfg or {}
    runner = _load_runner(provider_id)
    if runner is None:
        # No adapter module and no descriptor execution block. Declared stubs
        # (execution: {mode: stub}) get an honest stub runner upstream; a
        # provider with NEITHER is an error condition — never fabricate a
        # success-shaped "stubbed" result for it.
        raise AudiaGenticError(
            code="VAL-EXEC-002",
            kind="providers",
            message="provider has no execution adapter or descriptor execution block",
            details={"provider-id": provider_id},
        )

    # MO15 launch-env seam: resolve deferred env contributions only for the
    # duration of this launch frame so the adapter's subprocess inherits them.
    # Stub providers never have registered contributions (recipe inertness
    # rule), so this is a no-op overlay for them.
    with launch_env_overlay(provider_id):
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
    normalized.setdefault("model", resolve_execution_model(packet_ctx, provider_cfg))
    normalized.setdefault("status", "ok")
    return normalized
