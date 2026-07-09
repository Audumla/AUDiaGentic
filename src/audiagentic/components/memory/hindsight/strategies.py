"""Hindsight strategy resolution and recipe construction.

Resolves the best integration strategy per provider from the matrix
(precedence: verified installer > mcp-config > fallback-mcp > rules-only,
with platform and source gates) and builds the matching recipe objects.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import (
    HINDSIGHT_RECIPE_MATRIX,
    HindsightRecipeRow,
)
from audiagentic.components.memory.hindsight.plugin_recipes import (
    PluginConfigRecipe,
    _PluginArrayRecipe,
    _PluginUrlConfigRecipe,
)
from audiagentic.components.memory.hindsight.recipe_spec import (
    ParamBinding,
    RecipeSpec,
    StatusOverride,
    assemble_hindsight_recipe,
)
from audiagentic.components.memory.hindsight.recipes import (
    _absolute_project_path,
    _McpConfigAdapter,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.recipes import ProviderRecipeKind
from audiagentic.foundation.toolchains.detect import platform_allowed

# ---------------------------------------------------------------------------
# RecipeSpec definitions for config-collapsible kinds (SL15)
# ---------------------------------------------------------------------------

#: Guidance-only spec: no automation, action-needed guidance.
# Both GuidanceOnly and former RulesOnly (now GUIDANCE_ONLY post-SL13 A7) use this pattern.
_GUIDANCE_SPEC = RecipeSpec(
    pattern="no_automation",
    params=[
        ParamBinding(param_name="action_needed", row_field="notes"),
        ParamBinding(param_name="skip_status", literal="skipped: no automated Hindsight integration for this provider"),
    ],
    status_overrides=[
        StatusOverride(method="probe", state="absent", status_text="no automated integration available"),
    ],
)

# The hooks (declared_step) spec is built per-row in _build_hooks_recipe because
# its `verified` / `source_label` bindings depend on the row's source_status.


def _platform_supported(row: HindsightRecipeRow) -> bool:
    """Check the current platform against the row's canonical constraints."""
    return platform_allowed(row.platform_constraints)


_INSTALLER_KINDS = (
    ProviderRecipeKind.HOOKS,
    ProviderRecipeKind.WRAPPER_CLI,
    ProviderRecipeKind.PLUGIN_CONFIG,
)


def _external_fallback_row(
    row: HindsightRecipeRow, provider_id: str, reason: str
) -> HindsightRecipeRow:
    """Downgrade an installer-style row so the provider points at the external
    Hindsight server without a local install: MCP config when the provider
    supports MCP, otherwise a rules-only block.
    """
    descriptor = get_descriptor(provider_id)
    # The fallback entry points at the external server (url-form), so it is
    # only viable when the provider's config can express remote entries.
    if descriptor and descriptor.mcp_config and descriptor.mcp_config.remote:
        return HindsightRecipeRow(
            provider_id=provider_id,
            display_name=row.display_name,
            integration_type="fallback-mcp",
            recipe_kind=ProviderRecipeKind.MCP_CONFIG,
            source_url=row.source_url,
            source_date=row.source_date,
            source_status="unconfirmed",
            audia_action="manage_config_writes",
            notes=reason,
        )
    return HindsightRecipeRow(
        provider_id=provider_id,
        display_name=row.display_name,
        integration_type="rules-only",
        recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
        source_url=row.source_url,
        source_date=row.source_date,
        source_status="unconfirmed",
        audia_action="action_needed",
        notes=reason,
    )


def resolve_hindsight_strategy(
    provider_id: str,
    project_root: Path | None = None,
) -> HindsightRecipeRow | None:
    """Resolve the best Hindsight strategy for a provider.

    Precedence: verified native/installer > mcp-config > fallback-mcp > rules-only.
    Platform gate drops unsupported installer strategies and falls back to
    pointing at the external server via MCP/rules. Source gate is enforced by
    the builder.
    """
    rows = [row for row in HINDSIGHT_RECIPE_MATRIX if row.provider_id == provider_id]
    if not rows:
        return None

    row = rows[0]  # one row per provider

    if row.recipe_kind in _INSTALLER_KINDS and not _platform_supported(row):
        return _external_fallback_row(
            row, provider_id,
            f"platform-gated ({', '.join(row.platform_constraints)}); external fallback",
        )

    return row


def _build_hooks_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
) -> Any:
    """Build hooks recipe with source gate.

    Assembles a per-row declared_step spec. The DeclaredStepRecipe enforces the
    verification gate natively: verified=False makes install() refuse with the
    original "refusing to execute" error, so no separate guidance fallback is
    needed here.
    """
    if row.provider_id == "codex":
        from audiagentic.components.memory.hindsight.codex_recipe import CodexHindsightRecipe

        return CodexHindsightRecipe(row, backend)
    if row.provider_id == "pi":
        from audiagentic.components.memory.hindsight.pi_recipe import PiHindsightRecipe

        return PiHindsightRecipe(row, backend)
    if row.provider_id == "aider" and sys.version_info >= (3, 13):
        blocked = replace(
            row,
            recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
            source_status="blocked",
            audia_action="action_needed",
            notes=(
                "Hindsight Aider installer is skipped on Python 3.13+. "
                "The current hindsight-aider/aider-chat dependency chain pulls "
                "old pinned build dependencies that fail under Python 3.13; "
                "use Python 3.12 or wait for an updated Hindsight Aider package."
            ),
        )
        return assemble_hindsight_recipe(blocked, None, _GUIDANCE_SPEC)

    from audiagentic.components.memory.hindsight.recipe_spec import ParamBinding, RecipeSpec

    is_verified = row.source_status == "verified"
    spec = RecipeSpec(
        pattern="declared_step",
        params=[
            ParamBinding(param_name="install_steps", row_field="install_steps"),
            ParamBinding(param_name="uninstall_steps", row_field="uninstall_steps"),
            ParamBinding(param_name="status_command", row_field="status_command"),
            ParamBinding("verified", literal=is_verified),
            ParamBinding("source_label", literal=row.source_status or ""),
            ParamBinding(param_name="gate_action", row_field="notes"),
        ],
        status_overrides=[
            StatusOverride(method="configure", state="configuring", status_text="hooks installed via CLI; no config write needed"),
            StatusOverride(method="prune", state="absent", status_text="hooks managed by CLI; no config to prune"),
            StatusOverride(method="dry_run", state="absent", status_text="would run install steps (dry-run)"),
        ],
    )
    return assemble_hindsight_recipe(row, backend, spec)


def _build_plugin_url_config_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    url_config_path: str | Path,
    harness_config_path: str | Path | None = None,
) -> Any:
    """Build Plugin URL config recipe with optional Windows repair."""
    return _PluginUrlConfigRecipe(
        row, backend, url_config_path,
        harness_config_path=harness_config_path,
    )


def _build_plugin_config_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None,
) -> Any:
    """Build plugin config recipe from metadata.

    Prefers plugin_array > url_config_path > generic MCP target fallback.
    Source gate applies only when install_steps are present and unverified.
    """
    harness_path = _resolve_harness_config_path(provider_id, project_root)
    if row.source_status != "verified" and row.install_steps:
        return assemble_hindsight_recipe(row, backend, _GUIDANCE_SPEC)
    if row.plugin_array_package and harness_path:
        return _PluginArrayRecipe(row, backend, harness_path)
    if row.plugin_url_config_path:
        return _build_plugin_url_config_recipe(
            row, backend, row.plugin_url_config_path,
            harness_path or row.plugin_url_config_path,
        )
    if harness_path:
        return PluginConfigRecipe(row, backend, Path(harness_path))
    return assemble_hindsight_recipe(row, backend, _GUIDANCE_SPEC)


def _build_mcp_config_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None,
) -> Any:
    """Build MCP-config recipe.

    Blocked source status returns guidance-only. After SL13 A8, HYBRID collapses
    to _McpConfigAdapter (rules flow via surface contributions).
    """
    if row.source_status == "blocked":
        return assemble_hindsight_recipe(row, backend, _GUIDANCE_SPEC)
    harness_path = _resolve_harness_config_path(provider_id, project_root)
    return _build_mcp_recipe(
        row, backend, provider_id, project_root, harness_path, None,
    )


def _build_guidance_only_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None,
) -> Any:
    """Build guidance-only recipe via config-driven assembly.

    After SL13 A7: rules content flows via surface contributions (memory.yaml).
    There is no rules-writing recipe — every guidance/rules strategy resolves to
    the no_automation pattern assembled from _GUIDANCE_SPEC.
    """
    return assemble_hindsight_recipe(row, backend, _GUIDANCE_SPEC)


# Factory registry keyed by ProviderRecipeKind.
# Each entry is a callable that accepts (row, backend, provider_id, project_root)
# and returns a recipe instance.
_RecipeFactory = Callable[
    [HindsightRecipeRow, HindsightBackendConfig, str, Path | None], Any
]

_RECIPE_FACTORIES: dict[ProviderRecipeKind, _RecipeFactory] = {
    ProviderRecipeKind.HOOKS: lambda r, b, p, pr: _build_hooks_recipe(r, b),
    ProviderRecipeKind.WRAPPER_CLI: lambda r, b, p, pr: _build_hooks_recipe(r, b),
    ProviderRecipeKind.PLUGIN_CONFIG: _build_plugin_config_recipe,
    ProviderRecipeKind.MCP_CONFIG: _build_mcp_config_recipe,
    ProviderRecipeKind.HYBRID: _build_mcp_config_recipe,
    ProviderRecipeKind.GUIDANCE_ONLY: _build_guidance_only_recipe,
}


def build_hindsight_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None = None,
) -> Any:
    """Build a recipe object for a resolved Hindsight strategy row.

    Dispatches through _RECIPE_FACTORIES keyed by ProviderRecipeKind.
    Unknown kinds fall back to the guidance-only (_GUIDANCE_SPEC) default.
    """
    factory = _RECIPE_FACTORIES.get(row.recipe_kind)
    if factory is not None:
        return factory(row, backend, provider_id, project_root)
    return assemble_hindsight_recipe(row, backend, _GUIDANCE_SPEC)


def _build_mcp_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None,
    harness_path: str | None,
    rule_path: Path | None,
) -> Any:
    """Build MCP-config recipe for MCP_CONFIG or HYBRID kind.

    After SL13 A8: _CompositeRecipe collapsed into _McpConfigAdapter — rules
    content flows via surface contributions (memory.yaml), so HYBRID is
    equivalent to MCP_CONFIG. Falls back to guidance when paths are unavailable.
    """
    descriptor = get_descriptor(provider_id)
    spec = descriptor.mcp_config if descriptor else None
    # A remote (url-form) entry cannot be expressed in a stdio-only provider
    # config — fall through to the guidance path instead of writing a broken
    # entry (audit finding, HM21/RV155).
    if spec is not None and not spec.remote and backend.transport != "stdio":
        harness_path = None
    if harness_path:
        config_path = Path(harness_path)
        return _McpConfigAdapter(row, backend, config_path, project_root=project_root)
    return assemble_hindsight_recipe(row, backend, _GUIDANCE_SPEC)


def _resolve_harness_config_path(provider_id: str, project_root: Path | None = None) -> str | None:
    """Resolve the real harness config path for a provider from its descriptor.

    The path is anchored to ``project_root`` so provisioning writes inside the
    target project, never relative to the current working directory.
    """
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return None
    spec = descriptor.mcp_config
    if spec is None:
        return None
    config_path = spec.config_path
    resolved = config_path(project_root) if callable(config_path) else config_path
    if resolved is None:
        return None
    return str(_absolute_project_path(resolved, Path(project_root) if project_root else None))


def _resolve_rule_path(provider_id: str, project_root: Path | None = None) -> Path | None:
    """Resolve a provider instruction/rules file from generic descriptor metadata."""
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return None
    rel_path = descriptor.instruction_file
    if rel_path is None:
        for agent_file in descriptor.agent_files:
            if agent_file.managed and agent_file.rel_path.lower().endswith((".md", ".mdx")):
                rel_path = agent_file.rel_path
                break
    if rel_path is None:
        return None
    return _absolute_project_path(rel_path, Path(project_root) if project_root else None)


__all__ = [
    "build_hindsight_recipe",
    "resolve_hindsight_strategy",
]
