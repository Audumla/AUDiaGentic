"""Hindsight provisioning lifecycle: register, apply, teardown, prune."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.export import (
    HindsightBackendConfig,
    build_hindsight_backend,
)
from audiagentic.components.memory.hindsight.matrix import HINDSIGHT_RECIPE_MATRIX
from audiagentic.components.memory.hindsight.mcp_recipe import (
    build_hindsight_managed_entry,
    hindsight_ownership_scope,
)
from audiagentic.components.memory.hindsight.recipe_spec import (
    ParamBinding,
    RecipeSpec,
    StatusOverride,
    assemble_hindsight_recipe,
)
from audiagentic.components.memory.hindsight.strategies import (
    build_hindsight_recipe,
    resolve_hindsight_strategy,
)
from audiagentic.components.providers.providers_api import ManagedMcpRequest, manage_mcp_entries
from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
    ProviderRecipeRegistry,
    ProviderRecipeResult,
    RecipeState,
)

#: Inline guidance-only spec for the no-backend fallback path in lifecycle.
#: Matches strategies._GUIDANCE_SPEC but defined here to avoid circular imports.
_NO_BACKEND_GUIDANCE_SPEC = RecipeSpec(
    pattern="no_automation",
    params=[
        ParamBinding(param_name="action_needed", row_field="notes"),
        ParamBinding(param_name="skip_status", literal="skipped: no automated Hindsight integration for this provider"),
    ],
    status_overrides=[
        StatusOverride(method="probe", state="absent", status_text="no automated integration available"),
    ],
)


def register_hindsight_recipes(
    registry: ProviderRecipeRegistry,
    backend: HindsightBackendConfig | None = None,
    project_root: Path | None = None,
) -> list[Any]:
    """Register Hindsight recipes for providers that have matrix rows.

    Uses resolve_hindsight_strategy + build_hindsight_recipe for each provider.
    Applies platform gate and source gate automatically.
    Returns the list of registered recipes.
    """
    if backend is None and project_root:
        backend = build_hindsight_backend(project_root)

    registered: list[Any] = []

    for row in HINDSIGHT_RECIPE_MATRIX:
        resolved = resolve_hindsight_strategy(row.provider_id, project_root)
        if resolved is None:
            continue

        if backend and resolved.recipe_kind in {
            ProviderRecipeKind.MCP_CONFIG,
            ProviderRecipeKind.HYBRID,
        }:
            continue

        if not backend:
            recipe = assemble_hindsight_recipe(resolved, None, _NO_BACKEND_GUIDANCE_SPEC)  # type: ignore[arg-type]
        else:
            recipe = build_hindsight_recipe(resolved, backend, resolved.provider_id, project_root)

        registry.register(recipe)
        registered.append(recipe)

    return registered


def _reconcile(
    project_root: Path,
    operation: str,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Central registry setup + dispatch for apply/teardown/prune operations.

    ``operation`` is one of: 'install', 'uninstall', 'prune'.
    For install/uninstall the registry lifecycle (probe → ops → verify) runs via
    ``_RowRecipe.provision/teardown``.  For prune only the prune primitive runs
    to avoid executing command-based uninstallers on stale config.
    """
    registry = ProviderRecipeRegistry()
    recipes = register_hindsight_recipes(
        registry,
        backend=backend,
        project_root=project_root,
    )
    selected = set(provider_ids) if provider_ids is not None else None
    ctx = context or {}
    results: dict[str, ProviderRecipeResult] = {}
    for recipe in recipes:
        if selected is not None and recipe.provider_id not in selected:
            continue
        if operation == "prune":
            # Stamp the primitive result at this boundary (SL11) so prune()
            # can return a plain RecipeResult.
            results[recipe.provider_id] = recipe.to_result(recipe.prune(ctx))
        elif operation == "uninstall":
            result = registry.uninstall(
                recipe.provider_id, recipe.capability_id, recipe.backend_id, ctx
            )
            results[recipe.provider_id] = result if result else ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="nothing to uninstall",
            )
        else:  # install
            result = registry.install(
                recipe.provider_id, recipe.capability_id, recipe.backend_id, ctx
            )
            results[recipe.provider_id] = result if result else ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="nothing to install",
            )

    if backend is not None:
        for row in HINDSIGHT_RECIPE_MATRIX:
            resolved = resolve_hindsight_strategy(row.provider_id, project_root)
            if resolved is None or resolved.recipe_kind not in {
                ProviderRecipeKind.MCP_CONFIG,
                ProviderRecipeKind.HYBRID,
            }:
                continue
            if selected is not None and resolved.provider_id not in selected:
                continue
            mode = "apply" if operation == "install" else "prune"
            family = manage_mcp_entries(
                project_root,
                resolved.provider_id,
                mode=mode,
                request=ManagedMcpRequest(
                    ownership_scope=hindsight_ownership_scope(backend),
                    entries=(build_hindsight_managed_entry(backend),) if mode == "apply" else (),
                ),
            )
            if family.ok:
                results[resolved.provider_id] = ProviderRecipeResult.ok(
                    RecipeState.VERIFIED if mode == "apply" else RecipeState.ABSENT,
                    status="managed MCP entry applied" if mode == "apply" else "managed MCP entry pruned",
                    action_needed=family.action_needed or "",
                )
            else:
                results[resolved.provider_id] = ProviderRecipeResult.fail(
                    family.error_code or "managed MCP operation failed",
                    action_needed=family.action_needed or "",
                )
    return results


def apply_hindsight(
    project_root: Path,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Provision Hindsight recipes from the contained memory implementation."""
    return _reconcile(
        project_root, "install",
        backend=backend, provider_ids=provider_ids, context=context,
    )


def teardown_hindsight(
    project_root: Path,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Remove Hindsight artifacts managed by the contained memory implementation."""
    return _reconcile(
        project_root, "uninstall",
        backend=backend, provider_ids=provider_ids, context=context,
    )


def prune_hindsight(
    project_root: Path,
    *,
    backend: HindsightBackendConfig | None = None,
    provider_ids: list[str] | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, ProviderRecipeResult]:
    """Remove only Hindsight *config* artifacts (MCP entries, rule blocks).

    Unlike :func:`teardown_hindsight`, this runs each recipe's ``prune`` only —
    never a command-based uninstaller. It is safe and idempotent, used to clear
    stale config from providers that are no longer enabled without executing
    destructive package uninstalls that may never have installed anything.
    """
    return _reconcile(
        project_root, "prune",
        backend=backend, provider_ids=provider_ids, context=context,
    )


__all__ = [
    "apply_hindsight",
    "prune_hindsight",
    "register_hindsight_recipes",
    "teardown_hindsight",
]
