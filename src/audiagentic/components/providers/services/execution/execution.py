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


def _adapter_hook(provider_id: str, submodule: str, fn_name: str) -> Callable[..., Any] | None:
    """Return ``adapters/<id>/<submodule>.<fn_name>`` if present, else None.

    The single find_spec+import+getattr helper behind every provider adapter
    hook (one-shot run, ACP/interactive launch builders, MCP surface, execution
    environment). Detection via find_spec avoids importing an absent module.
    """
    name = provider_id.replace("-", "_")
    if keyword.iskeyword(name):
        name = name + "_"
    module_path = f"{_ADAPTER_BASE}.{name}.{submodule}"
    try:
        if not importlib.util.find_spec(module_path):
            return None
    except (ModuleNotFoundError, AttributeError):
        return None
    return getattr(import_module(module_path), fn_name, None)


def _load_runner(provider_id: str) -> ProviderRunner | None:
    module_path = _adapter_module_path(provider_id)
    if module_path is None:
        return _descriptor_runner(provider_id)
    runner = _adapter_hook(provider_id, "adapter", "run")
    if runner is None:
        raise AudiaGenticError(
            code="INT-EXEC-001",
            kind="providers",
            message="provider adapter is missing a run entrypoint",
            details={"provider-id": provider_id, "module": module_path},
        )
    return runner


# Launch profiles whose builder submodule/recipe key differs from the
# caller-facing profile name -- "agent" is built via the "acp" submodule/recipe
# block, since ACP is the transport this provider happens to use, not the
# name callers ask for. Predates the adapters/<id>/<name>.py convention below.
# New launch profiles need no entry here.
_LAUNCH_BUILDERS: dict[str, tuple[str, str]] = {
    "interactive": ("interactive", "build_interactive_launch"),
    "agent": ("acp", "build_acp_launch"),
}


def _declared_launches(provider_id: str) -> dict[str, Any]:
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    descriptor = all_descriptors().get(provider_id)
    declared = getattr(descriptor, "launches", None) if descriptor else None
    return declared or {}


def resolve_launch_builder(provider_id: str, name: str) -> Callable[..., Any] | None:
    """Resolve the builder for one provider launch profile, by name.

    Launch profiles are open-ended, not a closed enum -- there is no
    "unknown profile" error. Capability (the descriptor's declared
    ``launches``) is the source of truth for what's actually supported: an
    undeclared name is unsupported (None, no probing); a declared name with
    no builder/recipe fails closed. An empty ``launches`` (undeclared,
    migration default) falls back to probing.

    "execute" resolves through ``_load_runner`` -- a full runner (build spec
    + spawn + parse), not just a spec-builder like the others. It has its own
    dedicated caller (``execute_provider``) that never selects it by name;
    it's reachable here mainly for introspection/consistency.

    Every other profile: a hand-written ``adapters/<id>/<submodule>`` builder
    (the escape hatch) wins; otherwise the declarative recipe block of the
    same key. "interactive"/"agent" use the legacy submodule/key mapping
    above (predating this convention); any other name is tried directly as
    both the submodule name and entry point (``adapters/<id>/<name>.py::build_launch``)
    -- add a new launch profile by dropping in that file, no registry edit.
    """
    declared = _declared_launches(provider_id)
    if declared and name not in declared:
        return None  # explicitly not a supported launch profile for this provider

    if name == "execute":
        # Execute's builder is a full runner (build spec + spawn + parse), and
        # _load_runner carries the missing-run-entrypoint guard.
        builder = _load_runner(provider_id)
    else:
        submodule, fn_name = _LAUNCH_BUILDERS.get(name, (name, "build_launch"))
        builder = _adapter_hook(provider_id, submodule, fn_name)
        if builder is None:
            from audiagentic.components.providers.adapters.recipe_launch import (
                descriptor_launch_builder,
            )

            builder = descriptor_launch_builder(provider_id, submodule)

    if declared and name in declared and builder is None:
        raise AudiaGenticError(
            code="INT-EXEC-003",
            kind="providers",
            message="provider declares this launch profile but has no builder or recipe",
            details={"provider-id": provider_id, "launch": name},
        )
    return builder


def load_acp_launch_builder(provider_id: str) -> Callable[..., Any] | None:
    """Back-compat wrapper: the agent-intent launch builder (ACP today)."""
    return resolve_launch_builder(provider_id, "agent")


def load_interactive_launch_builder(provider_id: str) -> Callable[..., Any] | None:
    """Back-compat wrapper: the interactive-intent launch builder."""
    return resolve_launch_builder(provider_id, "interactive")


def load_mcp_surface_builder(provider_id: str) -> Callable[..., Any] | None:
    """Return the provider's MCP launch-surface builder, if it has one.

    An adapter package that can build an AUDiaGentic-curated MCP launch surface
    exposes ``prepare_mcp_surface(request) -> McpLaunchSurfaceResult`` in its
    ``mcp_surface`` submodule. Not a launch *kind* — a separate capability hook
    — so it stays its own loader over the shared ``_adapter_hook`` helper.
    """
    return _adapter_hook(provider_id, "mcp_surface", "prepare_mcp_surface")


def load_execution_environment_builder(provider_id: str) -> Callable[..., Any] | None:
    """Load an optional provider-owned isolated-worker environment builder."""
    return _adapter_hook(provider_id, "execution_environment", "build_execution_environment")


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
    from .launch_env import launch_env_overlay

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
