"""Sanctioned public-API module for requester components (arch §18).

This is the **only** `audiagentic.components.providers.*` import path that
requester components (memory, coding-lsp, runtime bootstrap, release) may use.
Never import adapters, services internals, serializers, capability config,
or handlers from a requester component — they are forbidden by architecture §18.

This module exposes provider-owned public operations and reads only. Recipes,
recipe kinds, registries, and their lifecycle methods are provider internals.
Requesters express semantic intent through the relevant family operation; they
never construct or dispatch a recipe.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.cli_lifecycle import (
    CliLifecycleMode,
    CliLifecycleRequest,
    CliLifecycleResult,
)
from audiagentic.components.providers.contracts.generated_surface import (
    GeneratedSurfaceMode,
    GeneratedSurfaceRequest,
    GeneratedSurfaceResult,
)
from audiagentic.components.providers.contracts.harness_status_observer import (
    HarnessStatusObserverCapability,
    normalize_harness_status_observation,
)
from audiagentic.components.providers.contracts.language_server_projection import (
    LanguageServerEntry,
    LanguageServerProjectionMode,
    LanguageServerProjectionRequest,
    LanguageServerProjectionResult,
)
from audiagentic.components.providers.contracts.managed_hooks import (
    ManagedHooksEntry,
    ManagedHooksMode,
    ManagedHooksRequest,
    ManagedHooksResult,
)
from audiagentic.components.providers.contracts.managed_mcp import (
    ManagedMcpEntry,
    ManagedMcpMode,
    ManagedMcpRequest,
    ManagedMcpResult,
)
from audiagentic.components.providers.contracts.mcp_launch_surface import (
    McpLaunchServerEntry,
    McpLaunchSurfaceResult,
)
from audiagentic.components.providers.contracts.model_projection import (
    ModelProjectionEntry,
    ModelProjectionMode,
    ModelProjectionRequest,
    ModelProjectionResult,
)
from audiagentic.components.providers.contracts.plugin_entry import (
    PluginEntryMode,
    PluginEntryRequest,
    PluginEntryResult,
)
from audiagentic.components.providers.contracts.provider_execution import (
    ProviderAcpLaunchResult,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderIsolationTier,
)
from audiagentic.components.providers.contracts.self_provided_lsp import (
    SelfProvidedLspMode,
    SelfProvidedLspRequest,
    SelfProvidedLspResult,
)
from audiagentic.components.providers.contracts.session_surface import (
    ResolvedSessionSurface,
    SurfaceHint,
)
from audiagentic.foundation.transports import ProviderLaunch
from audiagentic.foundation.transports.harness_status_observer import (
    StatusObserverLease,
    StatusObserverRequest,
    StatusObserverResult,
)
from audiagentic.foundation.transports.session_surface import PreparedSessionTransport


def get_provider_execution_isolation_tier(provider_id: str) -> ProviderIsolationTier:
    """Return the provider-wide execution isolation fact."""
    from audiagentic.components.providers.services.execution.public_execution import (
        get_provider_execution_isolation_tier as _get_tier,
    )

    return _get_tier(provider_id)


def get_provider_runtime_config_state(
    project_root: Path,
    provider_id: str,
) -> dict[str, Any]:
    """Return provider-scoped runtime configuration state for fingerprinting."""
    from audiagentic.components.providers.services.execution.public_execution import (
        get_provider_runtime_config_state as _get_state,
    )

    return _get_state(project_root, provider_id)


def execute_provider_turn(request: ProviderExecutionRequest) -> ProviderExecutionResult:
    """Execute one provider turn through the sanctioned public boundary."""
    from audiagentic.components.providers.services.execution.public_execution import (
        execute_provider_turn as _execute,
    )

    return _execute(request)


def prepare_provider_execution_environment(
    request: ProviderExecutionRequest,
) -> dict[str, str]:
    """Return transient provider-owned variables for an isolated worker."""
    from audiagentic.components.providers.services.execution.public_execution import (
        prepare_provider_execution_environment as _prepare,
    )

    return _prepare(request)


def list_canonical_provider_ids() -> tuple[str, ...]:
    """Return provider ids accepted by provider-backed prompt launches."""
    from audiagentic.components.providers.services.execution.public_prompt_operations import (
        list_canonical_provider_ids as _list,
    )

    return _list()


def get_prompt_syntax_defaults() -> dict[str, Any]:
    """Return provider-owned defaults for shared prompt syntax parsing."""
    from audiagentic.components.providers.services.execution.public_prompt_operations import (
        get_prompt_syntax_defaults as _get,
    )

    return _get()


def load_prompt_syntax(
    project_root: Path | None,
    profile_name: str | None = None,
) -> dict[str, Any]:
    """Load the provider-owned prompt syntax document and project overlay."""
    from audiagentic.components.providers.services.execution.prompt_syntax import (
        load_prompt_syntax as _load,
    )

    return _load(project_root, profile_name)


def get_provider_prompt_settings_profile(
    project_root: Path,
    provider_id: str,
) -> str | None:
    """Return one provider's optional prompt-syntax settings profile."""
    from audiagentic.components.providers.services.execution.public_prompt_operations import (
        get_provider_prompt_settings_profile as _get,
    )

    return _get(project_root, provider_id)


def is_provider_enabled_for_launch(project_root: Path, provider_id: str) -> bool:
    """Return whether a provider is enabled for prompt launch resolution."""
    from audiagentic.components.providers.services.execution.public_prompt_operations import (
        is_provider_enabled_for_launch as _is_enabled,
    )

    return _is_enabled(project_root, provider_id)


def resolve_launch_model(
    project_root: Path,
    *,
    provider_id: str,
    model_id: str | None,
    model_alias: str | None,
) -> dict[str, Any]:
    """Resolve one launch model through provider-owned runtime configuration."""
    from audiagentic.components.providers.services.execution.public_prompt_operations import (
        resolve_launch_model as _resolve,
    )

    return _resolve(
        project_root,
        provider_id=provider_id,
        model_id=model_id,
        model_alias=model_alias,
    )


def load_packaged_prompt_template(
    tag: str,
    *,
    template_name: str | None,
) -> tuple[str, Path | None] | None:
    """Resolve a packaged provider-owned prompt template."""
    from audiagentic.components.providers.services.execution.public_prompt_operations import (
        load_packaged_prompt_template as _load,
    )

    return _load(tag, template_name=template_name)


def execute_provider_review_turn(
    project_root: Path,
    *,
    provider_id: str,
    packet_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Run a review-specific provider turn through the public boundary."""
    from audiagentic.components.providers.services.execution.public_prompt_operations import (
        execute_provider_review_turn as _execute,
    )

    return _execute(project_root, provider_id=provider_id, packet_data=packet_data)


def prepare_provider_acp_launch(
    project_root: Path,
    *,
    provider_id: str,
    model_id: str | None,
    model_alias: str | None,
    request_runtime_root: Path | None = None,
    mcp_entries: tuple[McpLaunchServerEntry, ...] | None = None,
    require_isolated_mcp: bool = False,
) -> ProviderAcpLaunchResult:
    """Prepare a provider-owned ACP launch for an agents-owned live session."""
    from audiagentic.components.providers.services.execution.public_execution import (
        prepare_provider_acp_launch as _prepare,
    )

    return _prepare(
        project_root,
        provider_id=provider_id,
        model_id=model_id,
        model_alias=model_alias,
        request_runtime_root=request_runtime_root,
        mcp_entries=mcp_entries,
        require_isolated_mcp=require_isolated_mcp,
    )


def prepare_interactive_provider_launch(
    project_root: Path,
    *,
    provider_id: str,
    provider: str,
    model: str,
    agent_runtime: Path,
    mcp_surface: McpLaunchSurfaceResult | None = None,
    runner_params: object | None = None,
    smoke: bool = False,
) -> ProviderLaunch:
    """Prepare a provider-owned interactive (TUI) CLI launch.

    For a runtime harness bootstrapping a human-facing session -- distinct
    from prepare_provider_acp_launch (headless RPC bridge for programmatic
    sessions). provider/model are already resolved by the caller from
    AUDiaGentic's own embedded rig config.
    """
    from audiagentic.components.providers.services.execution.public_execution import (
        prepare_interactive_provider_launch as _prepare,
    )

    return _prepare(
        project_root,
        provider_id=provider_id,
        provider=provider,
        model=model,
        agent_runtime=agent_runtime,
        mcp_surface=mcp_surface,
        runner_params=runner_params,
        smoke=smoke,
    )


def translate_interactive_runner_args(provider_id: str, runner_params: object) -> list[str]:
    """Translate generic TUI runner parameters through the provider boundary."""
    from audiagentic.components.providers.services.execution.public_execution import (
        translate_interactive_runner_args as _translate,
    )

    return _translate(provider_id, runner_params)


def materialize_provider_config(
    project_root: Path,
    provider_id: str,
    harness_cfg: dict,
    *,
    agent_runtime: Path | None = None,
) -> None:
    """Materialize a provider's own config files through the public boundary.

    Writes provider-specific config (e.g. models.json, settings.json for Pi;
    .opencode/config.json and AGENTS.md for OpenCode) and applies provider
    surface contributions. The provider adapter owns its own config shapes,
    templates, and delivery mechanism — this call routes through the adapter.

    Args:
        project_root: Project root for component discovery and surface apply.
        provider_id: Canonical provider identifier ("pi", "opencode").
        harness_cfg: Harness config dict (rig.model, rig.port, rig.provider).
        agent_runtime: Target directory for agent files (harness runtime root).
            Used by Pi which writes to a global harness runtime; ignored by
            OpenCode which writes project-local files.
    """
    from audiagentic.components.providers.services.lifecycle.public_materialize import (
        materialize_provider_config as _materialize,
    )

    _materialize(
        project_root,
        provider_id=provider_id,
        harness_cfg=harness_cfg,
        agent_runtime=agent_runtime,
    )


def prepare_provider_mcp_surface(
    project_root: Path,
    *,
    provider_id: str,
    entries: tuple[McpLaunchServerEntry, ...],
    runtime_root: Path | None = None,
    require_exact_isolation: bool = False,
) -> McpLaunchSurfaceResult:
    """Ask one provider to build an AUDiaGentic-curated MCP launch surface.

    The caller (interactive launcher, isolated-agent-job dispatch) computes
    WHICH servers belong in the surface and supplies them as *entries*; the
    provider decides HOW to deliver them for its own process (patched CLI
    flags, an env var, a generated file) without exposing that mechanism.
    Soft-fails to ``supported=False`` when the provider has none.
    """
    from audiagentic.components.providers.services.execution.public_execution import (
        prepare_provider_mcp_surface as _prepare,
    )

    return _prepare(
        project_root,
        provider_id=provider_id,
        entries=entries,
        runtime_root=runtime_root,
        require_exact_isolation=require_exact_isolation,
    )


def collect_management_mcp_launch_entries(
    project_root: Path,
) -> tuple[McpLaunchServerEntry, ...]:
    """Return the management projection as provider launch entries."""
    from audiagentic.components.providers.services.execution.public_execution import (
        collect_management_mcp_launch_entries as _collect,
    )

    return _collect(project_root)


def prepare_projected_provider_mcp_surface(
    project_root: Path,
    *,
    provider_id: str,
    runtime_root: Path | None,
    require_exact_isolation: bool = False,
) -> McpLaunchSurfaceResult:
    """Collect and materialize the standard projection for a provider launch."""
    from audiagentic.components.providers.services.execution.public_execution import (
        prepare_projected_provider_mcp_surface as _prepare,
    )

    return _prepare(
        project_root,
        provider_id=provider_id,
        runtime_root=runtime_root,
        require_exact_isolation=require_exact_isolation,
    )


def get_pi_coding_agent_package_dir() -> Path | None:
    """Return the system-installed pi-coding-agent package dir, or None."""
    from audiagentic.components.providers.services.execution.public_execution import (
        get_pi_coding_agent_package_dir as _get,
    )

    return _get()


def manage_plugin_entry(
    project_root: Path,
    provider_id: str,
    *,
    mode: PluginEntryMode,
    request: PluginEntryRequest,
) -> PluginEntryResult:
    """Manage one generic provider plugin-config entry."""
    from audiagentic.components.providers.services.capabilities.plugin_entries import (
        manage_plugin_entry as _manage,
    )

    return _manage(project_root, provider_id, mode=mode, request=request)


def manage_mcp_entries(
    project_root: Path,
    provider_id: str,
    *,
    mode: ManagedMcpMode,
    request: ManagedMcpRequest,
) -> ManagedMcpResult:
    """Manage caller-owned MCP entries through provider automation."""
    from audiagentic.components.providers.services.capabilities.managed_mcp_family import (
        manage_mcp_entries as _manage,
    )

    return _manage(
        project_root,
        provider_id,
        mode=mode,
        request=request,
    )


def adopt_legacy_mcp_ownership(
    project_root: Path,
    *,
    ownership_scope: str,
    managed_ids: frozenset[str],
) -> None:
    """Migrate MCP registry entries from legacy bare provider_id scope to scoped key.

    Call before first managed-mcp apply/prune if the old lsp-mcp-projection family
    may have written entries under the bare provider_id scope. The migration is
    idempotent — it only moves entries whose managed_id is in the caller's set.
    """
    from audiagentic.components.providers.services.capabilities.managed_mcp_family import (
        adopt_legacy_mcp_ownership as _adopt,
    )

    _adopt(
        project_root,
        ownership_scope=ownership_scope,
        managed_ids=managed_ids,
    )


def manage_hook_entries(
    project_root: Path,
    provider_id: str,
    *,
    mode: ManagedHooksMode,
    request: ManagedHooksRequest,
) -> ManagedHooksResult:
    """Manage caller-owned hook entries through provider automation."""
    from audiagentic.components.providers.services.capabilities.managed_hooks_family import (
        manage_hook_entries as _manage,
    )

    return _manage(
        project_root,
        provider_id,
        mode=mode,
        request=request,
    )


def manage_mcp_entries_all(
    project_root: Path,
    *,
    mode: ManagedMcpMode,
    request: ManagedMcpRequest,
) -> list[ManagedMcpResult]:
    """Manage MCP entries for all providers that support the managed-mcp family.

    Returns a list of per-provider results. Providers without mcp_config or
    the managed-mcp capability return ``supported=False``.
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    results: list[ManagedMcpResult] = []
    for descriptor in all_descriptors().values():
        if descriptor.mcp_config is None:
            continue
        result = manage_mcp_entries(
            project_root,
            descriptor.provider_id,
            mode=mode,
            request=request,
        )
        results.append(result)
    return results


def manage_language_servers(
    project_root: Path,
    provider_id: str,
    *,
    mode: LanguageServerProjectionMode,
    request: LanguageServerProjectionRequest,
) -> LanguageServerProjectionResult:
    """Manage caller-owned language server entries through provider automation."""
    from audiagentic.components.providers.services.capabilities.language_server_family import (
        manage_language_servers as _manage,
    )

    return _manage(
        project_root,
        provider_id,
        mode=mode,
        request=request,
    )


def manage_language_servers_all(
    project_root: Path,
    *,
    mode: LanguageServerProjectionMode,
    request: LanguageServerProjectionRequest,
) -> list[LanguageServerProjectionResult]:
    """Manage language server entries for all providers that support the family.

    Returns a list of per-provider results. Providers without language_servers_config
    are not included in the results.
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    results: list[LanguageServerProjectionResult] = []
    for descriptor in all_descriptors().values():
        if descriptor.language_servers_config is None:
            continue
        result = manage_language_servers(
            project_root,
            descriptor.provider_id,
            mode=mode,
            request=request,
        )
        results.append(result)
    return results


def manage_model_projection(
    project_root: Path,
    provider_id: str,
    *,
    mode: ModelProjectionMode,
    request: ModelProjectionRequest,
) -> ModelProjectionResult:
    """Manage caller-owned model entries through provider automation."""
    from audiagentic.components.providers.services.capabilities.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(project_root)
    result = registry.dispatch(
        provider_id,
        "model-projection",
        mode,
        request,
    )
    if isinstance(result, ModelProjectionResult):
        return result
    if isinstance(result, dict):
        return ModelProjectionResult(**result)
    return ModelProjectionResult(
        ok=False, supported=False, provider_id=provider_id, error_code="RES-PREC-001"
    )


def manage_self_provided_lsp(
    project_root: Path,
    provider_id: str,
    *,
    mode: SelfProvidedLspMode,
    request: SelfProvidedLspRequest,
) -> SelfProvidedLspResult:
    """Manage self-provided LSP support through provider automation."""
    from audiagentic.components.providers.services.capabilities.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(project_root)
    result = registry.dispatch(
        provider_id,
        "self-provided-lsp",
        mode,
        request,
    )
    if isinstance(result, SelfProvidedLspResult):
        return result
    if isinstance(result, dict):
        return SelfProvidedLspResult(**result)
    return SelfProvidedLspResult(
        ok=False, supported=False, provider_id=provider_id, error_code="RES-PREC-001"
    )


def manage_self_provided_lsp_all(
    project_root: Path,
    *,
    mode: SelfProvidedLspMode,
    request: SelfProvidedLspRequest,
) -> list[SelfProvidedLspResult]:
    """Manage self-provided LSP support for every known provider.

    Returns one result per provider so callers never need the descriptor
    registry or enablement state to interpret the outcome: providers that do
    not self-provide LSP come back ``supported=False``, and providers that are
    not enabled come back ``ok=False`` with ``action_needed``.
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors
    from audiagentic.components.providers.services.config.feature_resolution import (
        enabled_provider_ids,
    )

    enabled = enabled_provider_ids(project_root)
    results: list[SelfProvidedLspResult] = []
    for descriptor in sorted(all_descriptors().values(), key=lambda d: d.provider_id):
        pid = descriptor.provider_id
        if descriptor.on_lsp_enabled is None:
            results.append(
                SelfProvidedLspResult(
                    ok=False,
                    supported=False,
                    provider_id=pid,
                    error_code="RES-PREC-001",
                )
            )
            continue
        if pid not in enabled:
            results.append(
                SelfProvidedLspResult(
                    ok=False,
                    supported=True,
                    provider_id=pid,
                    action_needed="provider is not enabled",
                )
            )
            continue
        results.append(manage_self_provided_lsp(project_root, pid, mode=mode, request=request))
    return results


def operate_provider_surface(
    project_root: Path,
    provider_id: str,
    *,
    mode: GeneratedSurfaceMode,
    request: GeneratedSurfaceRequest,
) -> GeneratedSurfaceResult:
    """Operate on generated provider surfaces through the recipe family."""
    from audiagentic.components.providers.services.capabilities.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(project_root)
    result = registry.dispatch(
        provider_id,
        "generated-surfaces",
        mode,
        request,
        ownership_scope=provider_id,
    )
    if isinstance(result, GeneratedSurfaceResult):
        return result
    if isinstance(result, dict):
        return GeneratedSurfaceResult(**result)
    return GeneratedSurfaceResult(
        ok=False,
        supported=False,
        error_code="RES-PREC-001",
    )


def operate_provider_surfaces(
    project_root: Path,
    provider_id: str | None = None,
    *,
    mode: GeneratedSurfaceMode,
) -> GeneratedSurfaceResult | list[GeneratedSurfaceResult]:
    """Operate on generated surfaces for one or all active providers.

    When *provider_id* is given, a single typed operation is performed.
    When omitted, the operation is applied to every active surface provider
    and a list of results is returned.
    """
    from audiagentic.components.providers.surfaces.contributions import (
        load_surface_contributions,
    )
    from audiagentic.components.providers.surfaces.registry import (
        load_contribution_renderer_registry,
    )

    if provider_id:
        contributions = load_surface_contributions(project_root=project_root)
        contribution_ids = tuple(c.contribution_id for c in contributions)
        request = GeneratedSurfaceRequest(
            ownership_scope=provider_id,
            contribution_ids=contribution_ids or ("__all__",),
        )
        return operate_provider_surface(
            project_root,
            provider_id,
            mode=mode,
            request=request,
        )

    renderers = load_contribution_renderer_registry()
    results: list[GeneratedSurfaceResult] = []
    for pid in sorted(renderers):
        try:
            single = operate_provider_surfaces(
                project_root,
                provider_id=pid,
                mode=mode,
            )
            if isinstance(single, GeneratedSurfaceResult):
                results.append(single)
        except Exception:  # noqa: BLE001 — catch all provider errors (missing impl)
            # Provider has no implementation for this family — skip gracefully
            results.append(
                GeneratedSurfaceResult(
                    ok=False,
                    supported=False,
                    error_code="RES-PREC-001",
                )
            )
    return results


def get_reconciliation_policy(project_root: Path) -> dict[str, Any]:
    """Return this project's provider reconciliation policy (defaults to auto)."""
    from audiagentic.components.providers.services.config.provider_config import (
        get_reconciliation_policy as _get,
    )

    return _get(project_root)


def set_reconciliation_policy(
    project_root: Path,
    *,
    mode: str,
    allowed_providers: list[str] | None = None,
    decided_providers: list[str] | None = None,
) -> dict[str, Any]:
    """Set this project's provider reconciliation policy.

    mode='auto' enables whatever provider CLI is detected on launch (today's
    behavior). mode='allowlist' only auto-enables providers in
    allowed_providers. mode='prompt' is resolved interactively at launch
    (see resolve_reconciliation_policy).
    """
    from audiagentic.components.providers.services.config.provider_config import (
        set_reconciliation_policy as _set,
    )

    return _set(
        project_root,
        mode=mode,
        allowed_providers=allowed_providers,
        decided_providers=decided_providers,
    )


def list_providers(project_root: Path) -> dict[str, Any]:
    from audiagentic.components.providers.services.lifecycle.status import build_provider_status

    return build_provider_status(project_root, include_probes=False)


def get_provider_status(project_root: Path, provider_id: str) -> dict[str, Any]:
    from audiagentic.components.providers.services.lifecycle.status import build_provider_status
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        payload = build_provider_status(project_root, provider_id, include_probes=True)
    except AudiaGenticError as exc:
        return {"provider_id": provider_id, "ok": False, "error": exc.message}
    providers = payload.get("providers", [])
    if providers:
        provider = providers[0]
        if isinstance(provider, dict):
            return provider
    return {"provider_id": provider_id, "ok": False, "error": "provider status unavailable"}


def list_provider_descriptors() -> list[dict[str, Any]]:
    from audiagentic.components.providers.descriptors import all_descriptors

    return [
        {
            "provider_id": descriptor.provider_id,
            "display_name": descriptor.display_name,
            "description": descriptor.description,
            "url": descriptor.url,
            "prompt_aliases": list(descriptor.prompt_aliases),
            "has_cli": descriptor.cli_probe is not None,
            "cli_probe": descriptor.cli_probe,
            "supports_catalog_fetch": descriptor.fetch_catalog_fn is not None,
            "automation_capabilities": [
                {
                    "family_id": capability.family_id,
                    "supported_modes": list(capability.supported_modes),
                    "payload_contract": capability.payload_contract,
                    "result_contract": capability.result_contract,
                    "ownership_scope_required": capability.ownership_scope_required,
                }
                for capability in descriptor.automation_capabilities
            ],
            "host_capabilities": [
                {
                    "host": capability.host,
                    "capability_id": capability.capability_id,
                    "display_name": capability.display_name,
                }
                for capability in descriptor.host_capabilities
            ],
            "host_extensions": {
                host: [
                    {"extension_id": e.capability_id, "display_name": e.display_name}
                    for e in descriptor.host_extensions(host)
                ]
                for host in sorted({c.host for c in descriptor.host_capabilities})
            },
            "permissions": {
                "can_write_files": descriptor.permissions.can_write_files,
                "can_execute_shell": descriptor.permissions.can_execute_shell,
                "can_browse_web": descriptor.permissions.can_browse_web,
                "can_read_env": descriptor.permissions.can_read_env,
                "notes": descriptor.permissions.notes,
            },
            "agent_files": [
                {
                    "rel_path": agent_file.rel_path,
                    "managed": agent_file.managed,
                    "description": agent_file.description,
                }
                for agent_file in descriptor.agent_files
            ],
        }
        for descriptor in sorted(all_descriptors().values(), key=lambda item: item.provider_id)
    ]


def list_provider_models(project_root: Path, provider_id: str) -> dict[str, Any]:
    """Read one provider catalog without fetching or writing durable state.

    Call :func:`refresh_provider_catalog` explicitly before this query when a
    fresh remote catalog is required.
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors
    from audiagentic.components.providers.services.config.provider_catalog import (
        catalog_is_stale,
        read_model_catalog,
    )
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    descriptor = all_descriptors().get(provider_id)
    if descriptor is None:
        return {
            "provider_id": provider_id,
            "models": [],
            "ok": False,
            "reason": "unknown-provider",
            "catalog_present": False,
            "stale": False,
        }
    if descriptor.fetch_catalog_fn is None:
        return {
            "provider_id": provider_id,
            "models": [],
            "ok": True,
            "reason": "no-catalog-support",
            "catalog_present": False,
            "stale": False,
        }

    try:
        catalog = read_model_catalog(project_root, provider_id)
    except AudiaGenticError:
        return {
            "provider_id": provider_id,
            "models": [],
            "ok": False,
            "reason": "no-catalog-found",
            "catalog_present": False,
            "stale": False,
        }

    models = [
        {
            "model_id": model.get("model-id", ""),
            "vendor_id": model.get("vendor-id", ""),
            "display_name": model.get("display-name", ""),
            "status": model.get("status", ""),
            "supports_structured_output": model.get("supports-structured-output", False),
            "context_window": model.get("context-window", 0),
        }
        for model in catalog.get("models", [])
    ]
    return {
        "provider_id": provider_id,
        "fetched_at": catalog.get("fetched-at", ""),
        "models": models,
        "ok": True,
        "reason": None,
        "catalog_present": True,
        "stale": catalog_is_stale(catalog, max_age_hours=24),
    }


async def refresh_provider_catalog(project_root: Path, provider_id: str) -> dict[str, Any]:
    from audiagentic.components.providers.services.catalog.catalog import fetch_provider_catalog

    try:
        return await asyncio.to_thread(
            fetch_provider_catalog, provider_id, project_root=project_root
        )
    except Exception as exc:  # noqa: BLE001
        return {"provider_id": provider_id, "ok": False, "error": str(exc)}


# --- provider interrogation (MO11) --------------------------------------------


def _serialize_config_surface(kind: str, spec, project_root: Path) -> dict[str, Any]:
    """Serialize one managed-config surface: {kind, configured, path_scope,
    resolved_path, format, refresh_mode} — never callable reprs or secret refs
    (MO11 step 3). Home prefixes redact to ``~``.

    ``transports`` is added only for the ``mcp`` kind, whose mechanism is an
    :class:`McpConfigSpec`; hooks, LSP configs, plugins and models have no
    transport concept and must not carry an invented one."""
    if spec is None:
        return {"kind": kind, "configured": False}
    from audiagentic.foundation.toolchains.config.managed_config import (
        resolve_managed_config_path,
    )

    entry: dict[str, Any] = {
        "kind": kind,
        "configured": True,
        "format": spec.format,
        "refresh_mode": spec.refresh_mode,
        "resolved_path": None,
        "path_scope": None,
    }
    transports = getattr(spec, "transports", None)
    if transports is not None:
        entry["transports"] = sorted(transports)
    try:
        resolved = resolve_managed_config_path(spec, project_root)
    except Exception:  # noqa: BLE001 — callable paths may need runtime context
        entry["path_scope"] = "unresolved"
        return entry
    home = Path.home()
    try:
        entry["resolved_path"] = "~/" + resolved.relative_to(home).as_posix()
        entry["path_scope"] = "home"
    except ValueError:
        entry["resolved_path"] = str(resolved)
        entry["path_scope"] = (
            "project"
            if not resolved.is_absolute() or str(resolved).startswith(str(project_root))
            else "absolute"
        )
    return entry


def _managed_registry_summary(name: str, registry, provider_id: str) -> dict[str, Any]:
    """Ownership registry names/counts only; corruption surfaces the canonical
    error code, never a silent empty claim (MO11 step 4)."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    try:
        owned = registry.load().get(provider_id, {})
    except AudiaGenticError as exc:
        return {"registry": name, "ok": False, "error_code": exc.code}
    return {"registry": name, "ok": True, "count": len(owned), "managed_ids": sorted(owned)}


def describe_provider(project_root: Path, provider_id: str) -> dict[str, Any]:
    """Deep read-only composition of existing provider-owned reads (MO11).

    Joins descriptor summary, status/probe, execution support, model catalog,
    managed-config surfaces, and ownership registries. Performs NO new
    discovery, NO duplicate probes/catalog parsing, and NO execution-profile join
    (agents owns profiles — ``related_tools`` points there instead).
    """
    from audiagentic.components.providers.descriptors.registry import get_descriptor
    from audiagentic.components.providers.services.catalog.models import (
        model_ownership_registry,
    )
    from audiagentic.components.providers.services.execution.execution import (
        describe_execution_support,
    )
    from audiagentic.components.providers.services.mcp.managed_mcp_registry import (
        mcp_ownership_registry,
    )

    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return {"provider_id": provider_id, "ok": False, "reason": "unknown-provider"}

    summary_rows = [row for row in list_provider_descriptors() if row["provider_id"] == provider_id]
    return {
        "provider_id": provider_id,
        "ok": True,
        "descriptor": summary_rows[0] if summary_rows else {},
        "status": get_provider_status(project_root, provider_id),
        "execution": describe_execution_support(provider_id),
        # HA04: queryable launch capability (intent -> channel surface by role).
        "launches": {
            intent: {role: list(channels) for role, channels in surface.items()}
            for intent, surface in (descriptor.launches or {}).items()
        },
        "models": list_provider_models(project_root, provider_id),
        "models_config": (
            manage_model_projection(
                project_root,
                provider_id,
                mode="status",
                request=ModelProjectionRequest(managed_ids=()),
            ).to_mapping()
            if descriptor.automation_capability("model-projection") is not None
            else {
                "ok": True,
                "supported": False,
                "provider_id": provider_id,
            }
        ),
        "config_surfaces": [
            _serialize_config_surface("mcp", descriptor.mcp_config, project_root),
            _serialize_config_surface(
                "language-servers", descriptor.language_servers_config, project_root
            ),
            _serialize_config_surface("models", descriptor.model_config, project_root),
        ],
        "managed": [
            _managed_registry_summary(
                "managed-mcp-servers", mcp_ownership_registry(project_root), provider_id
            ),
            _managed_registry_summary(
                "managed-model-endpoints", model_ownership_registry(project_root), provider_id
            ),
        ],
        "supported_connectors": list(descriptor.supported_connectors),
        # secrets.py scheme:locator reference strings (e.g. "env:OPENAI_API_KEY"),
        # never a resolved value.
        "vendor_key_injection": dict(descriptor.vendor_key_injection),
        "related_tools": ["agent_list_execution_profiles"],
    }


# --- model-source desired-state resources (MO02) -----------------------------
#
# CRUD owns only ``model-sources.yaml``. Provider-file mutation is an explicit
# call to the typed model-projection family above; resource operations never
# smuggle automation through ``apply`` or ``dry_run`` flags.


def _model_source_diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, list[str]]:
    old_sources = old.get("sources") or {}
    new_sources = new.get("sources") or {}
    return {
        "added": sorted(set(new_sources) - set(old_sources)),
        "removed": sorted(set(old_sources) - set(new_sources)),
        "changed": sorted(
            source_id
            for source_id in set(old_sources) & set(new_sources)
            if old_sources[source_id] != new_sources[source_id]
        ),
    }


def _mutate_model_sources(
    project_root: Path,
    mutate,
) -> dict[str, Any]:
    from audiagentic.components.providers.services.catalog.models import (
        record_model_config_timeline,
    )
    from audiagentic.components.providers.services.config.model_source_config import (
        load_model_sources,
        validate_model_sources,
        write_model_sources,
    )
    from audiagentic.foundation.contracts.errors import make_error

    current = load_model_sources(project_root)
    proposed = mutate(json_roundtrip(current))
    issues = validate_model_sources(proposed)
    if issues:
        raise make_error(
            prefix="VAL",
            component="MEP",
            number=1,
            kind="providers",
            message="model-sources.yaml failed schema validation",
            details={"issues": issues},
        )

    diff = _model_source_diff(current, proposed)
    write_model_sources(project_root, proposed)
    for source_id in diff["added"] + diff["changed"] + diff["removed"]:
        record_model_config_timeline(
            project_root,
            "model-sources",
            "model-config.planned",
            attributes={"source-id": source_id},
        )
    return {"ok": True, "diff": diff, "written": True}


def json_roundtrip(value: dict[str, Any]) -> dict[str, Any]:
    import copy

    return copy.deepcopy(value)


def model_source_list(project_root: Path) -> dict[str, Any]:
    from audiagentic.components.providers.services.config.model_source_config import (
        load_model_sources,
    )

    document = load_model_sources(project_root)
    sources = {
        source_id: {
            "source-class": source.get("source-class"),
            "display-name": source.get("display-name"),
            "vendor-id": source.get("vendor-id"),
            "connector": source.get("connector"),
            "model-discovery": source.get("model-discovery"),
            "model-id": source.get("model-id"),
            "enabled": source.get("enabled", True),
            "api-key-ref": source.get("api-key-ref"),
        }
        for source_id, source in (document.get("sources") or {}).items()
    }
    return {"ok": True, "contract-version": document.get("contract-version"), "sources": sources}


def list_model_inventory(project_root: Path) -> dict[str, Any]:
    """Show configured sources, vendor groups, models, and harness paths."""
    from audiagentic.components.providers.descriptors.registry import all_descriptors
    from audiagentic.components.providers.services.catalog.source_catalog import (
        apply_model_filter,
        get_source_catalog,
    )
    from audiagentic.components.providers.services.config.model_source_config import (
        load_model_sources,
    )

    descriptors = all_descriptors()
    provider_catalogs = {
        provider_id: list_provider_models(project_root, provider_id)
        for provider_id in sorted(descriptors)
    }
    vendor_harnesses: dict[str, set[str]] = {}
    vendor_models: dict[str, dict[str, dict[str, Any]]] = {}
    vendor_sources: dict[str, list[dict[str, Any]]] = {}
    for provider_id, catalog in provider_catalogs.items():
        if not catalog.get("ok"):
            continue
        for model in catalog.get("models", []):
            vendor_id = str(model.get("vendor_id") or "")
            if not vendor_id:
                continue
            vendor_harnesses.setdefault(vendor_id, set()).add(provider_id)
            vendor_models.setdefault(vendor_id, {})[str(model["model_id"])] = model

    sources: list[dict[str, Any]] = []
    document = load_model_sources(project_root)
    for source_id, source in sorted((document.get("sources") or {}).items()):
        if source.get("source-class") == "local-endpoint":
            models = [
                {
                    "model_id": source.get("model-id"),
                    "display_name": source.get("display-name") or source.get("model-id"),
                }
            ]
            freshness = "declared"
            action_needed = None
        else:
            try:
                catalog = get_source_catalog(project_root, source_id, source, refresh=False)
                selected = apply_model_filter(catalog.models, source.get("model-filter"))
                models = [
                    {
                        "model_id": model.get("model-id"),
                        "display_name": model.get("display-name") or model.get("model-id"),
                        "context_window": model.get("context-window"),
                    }
                    for model in selected
                ]
                freshness = catalog.freshness
                action_needed = catalog.action_needed
            except Exception as exc:  # noqa: BLE001 - inventory reports source failure
                models = []
                freshness = "invalid"
                action_needed = str(exc)

        vendor_id = str(source.get("vendor-id") or "")
        if vendor_id:
            vendor_sources.setdefault(vendor_id, []).append(
                {
                    "source_id": source_id,
                    "enabled": source.get("enabled", True),
                }
            )
            for model in models:
                model_id = str(model.get("model_id") or "")
                if model_id:
                    vendor_models.setdefault(vendor_id, {})[model_id] = model
        harnesses: dict[tuple[str, str], dict[str, Any]] = {}
        for provider_id, descriptor in sorted(descriptors.items()):
            if vendor_id and vendor_id in descriptor.vendor_key_injection:
                from audiagentic.components.providers.services.secrets import (
                    has_ambient_value,
                    parse_secret_ref,
                )

                ref = descriptor.vendor_key_injection[vendor_id]
                available = bool(ref and has_ambient_value(ref))
                harnesses[(provider_id, "native-vendor")] = {
                    "provider_id": provider_id,
                    "mode": "native-vendor",
                    "available": available,
                    "enabled": bool(source.get("enabled", True) and available),
                    "action_needed": None if available else f"set {parse_secret_ref(ref).locator}",
                }
            if (
                descriptor.automation_capability("model-projection") is not None
                and source.get("connector") in descriptor.supported_connectors
                and not (vendor_id and vendor_id in descriptor.vendor_key_injection)
            ):
                harnesses[(provider_id, "custom-entries")] = {
                    "provider_id": provider_id,
                    "mode": "custom-entries",
                    "available": True,
                    "enabled": bool(source.get("enabled", True)),
                    "action_needed": None,
                }
            if vendor_id and provider_id in vendor_harnesses.get(vendor_id, set()):
                harnesses[(provider_id, "native-catalog")] = {
                    "provider_id": provider_id,
                    "mode": "native-catalog",
                    "available": True,
                    "enabled": bool(source.get("enabled", True)),
                    "action_needed": None,
                }
        sources.append(
            {
                "source_id": source_id,
                "display_name": source.get("display-name") or source_id,
                "vendor_id": vendor_id or None,
                "source_class": source.get("source-class"),
                "connector": source.get("connector"),
                "enabled": source.get("enabled", True),
                "catalog_freshness": freshness,
                "action_needed": action_needed,
                "models": models,
                "harnesses": list(harnesses.values()),
            }
        )

    vendors = [
        {
            "vendor_id": vendor_id,
            "harnesses": sorted(vendor_harnesses.get(vendor_id, set())),
            "sources": vendor_sources.get(vendor_id, []),
            "enabled": any(item["enabled"] for item in vendor_sources.get(vendor_id, [])),
            "models": sorted(
                vendor_models.get(vendor_id, {}).values(),
                key=lambda item: item["model_id"],
            ),
        }
        for vendor_id in sorted(set(vendor_models) | set(vendor_sources))
    ]
    return {"ok": True, "sources": sources, "vendors": vendors}


def refresh_model_source_catalog(project_root: Path, source_id: str) -> dict[str, Any]:
    """Explicitly refresh one configured source catalog."""
    from audiagentic.components.providers.services.catalog.source_catalog import get_source_catalog
    from audiagentic.components.providers.services.config.model_source_config import (
        load_model_sources,
    )
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    source = (load_model_sources(project_root).get("sources") or {}).get(source_id)
    if source is None:
        raise AudiaGenticError(
            code="VAL-MEP-005",
            kind="providers",
            message="unknown model source",
            details={"source-id": source_id},
        )
    return get_source_catalog(project_root, source_id, source, refresh=True).to_dict()


def model_vendor_set_enabled(project_root: Path, vendor_id: str, enabled: bool) -> dict[str, Any]:
    """Enable or disable every configured source for one vendor group."""
    from audiagentic.foundation.contracts.errors import AudiaGenticError

    matched: list[str] = []

    def mutate(document: dict[str, Any]) -> dict[str, Any]:
        for source_id, source in (document.get("sources") or {}).items():
            if source.get("vendor-id") == vendor_id:
                source["enabled"] = enabled
                matched.append(source_id)
        if not matched:
            raise AudiaGenticError(
                code="VAL-MEP-006",
                kind="providers",
                message="vendor has no configured model source",
                details={"vendor-id": vendor_id},
            )
        return document

    result = _mutate_model_sources(project_root, mutate)
    result.update({"vendor_id": vendor_id, "enabled": enabled, "source_ids": matched})
    return result


def apply_model_sources(project_root: Path) -> dict[str, Any]:
    """Apply desired sources to every enabled registered model harness."""
    from audiagentic.components.providers.descriptors.registry import all_descriptors
    from audiagentic.components.providers.services.catalog.models import (
        build_model_projection_request,
    )
    from audiagentic.components.providers.services.config.provider_config import is_provider_enabled

    results: list[dict[str, Any]] = []
    for provider_id, descriptor in sorted(all_descriptors().items()):
        if descriptor.automation_capability("model-projection") is None:
            continue
        if not is_provider_enabled(project_root, provider_id):
            results.append(
                {
                    "provider_id": provider_id,
                    "ok": True,
                    "supported": True,
                    "skipped": "provider-disabled",
                }
            )
            continue
        request = build_model_projection_request(project_root, provider_id, enabled=True)
        results.append(
            manage_model_projection(
                project_root, provider_id, mode="apply", request=request
            ).to_mapping()
        )
    return {"ok": all(result.get("ok", False) for result in results), "results": results}


def model_source_add(
    project_root: Path,
    source_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    from audiagentic.foundation.contracts.errors import make_error

    def mutate(document: dict[str, Any]) -> dict[str, Any]:
        sources = document.setdefault("sources", {})
        if source_id in sources:
            raise make_error(
                prefix="VAL",
                component="MEP",
                number=1,
                kind="providers",
                message="model source already exists; use model_source_update",
                details={"source-id": source_id},
            )
        sources[source_id] = config
        return document

    return _mutate_model_sources(project_root, mutate)


def _require_source(document: dict[str, Any], source_id: str) -> dict[str, Any]:
    from audiagentic.foundation.contracts.errors import make_error

    sources = document.get("sources") or {}
    if source_id not in sources:
        raise make_error(
            prefix="VAL",
            component="MEP",
            number=1,
            kind="providers",
            message="unknown model source id",
            details={"source-id": source_id},
        )
    return sources


def model_source_update(
    project_root: Path,
    source_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    def mutate(document: dict[str, Any]) -> dict[str, Any]:
        sources = _require_source(document, source_id)
        sources[source_id].update(updates)
        return document

    return _mutate_model_sources(project_root, mutate)


def model_source_remove(
    project_root: Path,
    source_id: str,
) -> dict[str, Any]:
    def mutate(document: dict[str, Any]) -> dict[str, Any]:
        sources = _require_source(document, source_id)
        del sources[source_id]
        return document

    return _mutate_model_sources(project_root, mutate)


def model_source_set_enabled(
    project_root: Path,
    source_id: str,
    enabled: bool,
) -> dict[str, Any]:
    def mutate(document: dict[str, Any]) -> dict[str, Any]:
        sources = _require_source(document, source_id)
        sources[source_id]["enabled"] = enabled
        return document

    return _mutate_model_sources(project_root, mutate)


async def refresh_all_catalogs(project_root: Path) -> dict[str, Any]:
    from audiagentic.components.providers.services.catalog.catalog import (
        refresh_all_catalogs as _refresh,
    )

    return await asyncio.to_thread(_refresh, project_root=project_root)


async def manage_cli_lifecycle(
    project_root: Path, provider_id: str, *, mode: CliLifecycleMode
) -> CliLifecycleResult:
    from audiagentic.components.providers.services.capabilities.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(project_root)
    result = registry.dispatch(
        provider_id,
        "cli-lifecycle",
        mode,
        CliLifecycleRequest(),
    )
    if isinstance(result, CliLifecycleResult):
        return result
    if isinstance(result, dict):
        return CliLifecycleResult.from_mapping(result)
    return CliLifecycleResult(ok=False, supported=False, state="failed")


# --- AS29 slice 5a: resolved session-surface through public boundary --------


def resolve_session_surface(
    project_root: Path,
    provider_id: str,
    surface_hint: SurfaceHint,
) -> ResolvedSessionSurface:
    """Resolve a session-surface snapshot through the public boundary.

    Delegates to the resolver service and returns only frozen foundation
    snapshot types. Never raises — unsupported surfaces produce an
    ``UNSUPPORTED``-state snapshot with neutral version metadata.

    Args:
        project_root: Explicit project root for provider enablement checks.
        provider_id: Canonical provider identifier.
        surface_hint: Typed request carrying surface id and optional
            version/platform hints.

    Returns:
        A frozen :class:`ResolvedSessionSurface` instance.
    """
    from audiagentic.components.providers.services.session.session_surface_resolution import (
        resolve_session_surface as _resolve,
    )

    return _resolve(project_root, provider_id, surface_hint)


def prepare_provider_session_transport(
    project_root: Path,
    *,
    provider_id: str,
    surface_hint: SurfaceHint,
    model_id: str | None = None,
    model_alias: str | None = None,
    request_runtime_root: Path | None = None,
    mcp_entries: tuple[McpLaunchServerEntry, ...] | None = None,
    require_isolated_mcp: bool = False,
    resume_provider_ref: str | None = None,
    enable_observability_tap: bool = False,
) -> PreparedSessionTransport:
    """Prepare a session transport with resolved surface snapshot.

    Resolves the AS29 surface exactly once, then wires provider-local factory
    composition for supported ACP surfaces. Returns a typed
    :class:`PreparedSessionTransport` carrying:

    - ``surface`` — the same frozen :class:`ResolvedSessionSurface` snapshot.
    - ``effective_provider_ref`` — the resolved :class:`SessionSurfaceRef`.
    - ``transport`` — an :class:`AcpAgentSessionTransport` (implements
      :class:`AgentSessionTransport`) for supported ACP surfaces, or ``None``
      when the surface is unsupported.

    Unsupported-surface contract: disabled provider, missing factory,
    version/platform mismatch, unvalidated high-level, blocked declaration
    all produce ``transport=None``. No process is launched and no fallback
    to another surface occurs.

    Adapter refs are resolved provider-side only and never returned.

    Does not expose descriptor/adapter/protocol/native values.
    """
    from audiagentic.components.providers.services.execution.public_execution import (
        prepare_provider_session_transport as _prepare,
    )

    return _prepare(
        project_root,
        provider_id=provider_id,
        surface_hint=surface_hint,
        model_id=model_id,
        model_alias=model_alias,
        request_runtime_root=request_runtime_root,
        mcp_entries=mcp_entries,
        require_isolated_mcp=require_isolated_mcp,
        resume_provider_ref=resume_provider_ref,
        enable_observability_tap=enable_observability_tap,
    )


# ── AS19 Stage-2 Slice A: harness status observer resolution ────────

# In-memory lease store for open_harness_status_observer / close_harness_status_observer.
# Slice A uses an in-memory dict only; no durable registry (that is a future slice).
_observer_lease_store: dict[str, StatusObserverLease] = {}


def open_harness_status_observer(
    request: StatusObserverRequest,
    *,
    agents_enabled: bool = True,
) -> tuple[StatusObserverResult, StatusObserverLease | None]:
    """Open a harness status observer for the given session.

    Resolves a transport-observation (Recipe A) lease. On success returns both
    the StatusObserverResult and the StatusObserverLease; on failure returns
    the error result with lease=None.

    The lease's observe_transport callable normalizes TransportObservation values
    into canonical StatusEvidence. The lease is also stored in the in-memory
    store keyed by binding_id so close_harness_status_observer can invalidate it.

    Args:
        request: Observer request with project/provider/surface/session context.
        agents_enabled: Whether the agents component is enabled. Defaults to True;
            the caller should resolve this from its own lifecycle state.

    Returns:
        A tuple of (StatusObserverResult, StatusObserverLease | None).
        On success: (ok=True result, lease). On failure: (ok=False result, None).
    """
    from audiagentic.components.providers.services.session.harness_status_observer_resolution import (
        resolve_transport_observation_lease,
    )

    # Check provider enabled status via the public seam.
    try:
        provider_enabled = is_provider_enabled_for_launch(
            Path(request.project_root), request.provider_id
        )
    except Exception:  # noqa: BLE001 — treat any error as provider not enabled.
        provider_enabled = False

    result = resolve_transport_observation_lease(
        request,
        agents_enabled=agents_enabled,
        provider_enabled=provider_enabled,
    )

    if result.ok and result.binding_id is not None:
        # Build the lease and store it for later invalidation.
        lease = _build_transport_lease(result.binding_id)
        _observer_lease_store[result.binding_id] = lease
        return result, lease

    return result, None


def close_harness_status_observer(binding_id: str) -> None:
    """Invalidate a harness status observer binding.

    Removes the lease from the in-memory store. Idempotent — no error if
    the binding was already removed or never existed.

    Args:
        binding_id: The opaque binding ID from open_harness_status_observer.
    """
    _observer_lease_store.pop(binding_id, None)


def _build_transport_lease(binding_id: str) -> StatusObserverLease:
    """Build a transport observer lease for the given binding_id.

    Internal helper: wraps normalize_harness_status_observation so the
    in-memory store holds a callable lease that can be queried.

    Args:
        binding_id: The binding ID to embed in the lease.

    Returns:
        A StatusObserverLease with observe_transport wired to the normalizer.
    """

    def _observe(observation):
        return normalize_harness_status_observation(lease, observation)

    lease = StatusObserverLease(
        binding_id=binding_id,
        observe_transport=_observe,
    )
    return lease


__all__ = [
    # One-shot provider execution
    "PreparedSessionTransport",
    "ProviderExecutionRequest",
    "ProviderExecutionResult",
    "ProviderAcpLaunchResult",
    "ProviderIsolationTier",
    "get_provider_execution_isolation_tier",
    "get_provider_runtime_config_state",
    "execute_provider_turn",
    "prepare_provider_acp_launch",
    "prepare_interactive_provider_launch",
    "ProviderLaunch",
    "prepare_provider_session_transport",
    "prepare_provider_execution_environment",
    "McpLaunchServerEntry",
    "McpLaunchSurfaceResult",
    "prepare_provider_mcp_surface",
    "collect_management_mcp_launch_entries",
    "prepare_projected_provider_mcp_surface",
    "get_pi_coding_agent_package_dir",
    # Prompt launch/query operations
    "list_canonical_provider_ids",
    "get_prompt_syntax_defaults",
    "load_prompt_syntax",
    "get_provider_prompt_settings_profile",
    "is_provider_enabled_for_launch",
    "resolve_launch_model",
    "load_packaged_prompt_template",
    "execute_provider_review_turn",
    "list_providers",
    "get_provider_status",
    "get_reconciliation_policy",
    "set_reconciliation_policy",
    "list_provider_descriptors",
    "list_provider_models",
    "refresh_provider_catalog",
    "describe_provider",
    # Model source management (MO02)
    "model_source_list",
    "list_model_inventory",
    "refresh_model_source_catalog",
    "model_vendor_set_enabled",
    "apply_model_sources",
    "model_source_add",
    "model_source_update",
    "model_source_remove",
    "model_source_set_enabled",
    "refresh_all_catalogs",
    # Provider lifecycle
    "CliLifecycleRequest",
    "CliLifecycleResult",
    "manage_cli_lifecycle",
    # AS29 slice 5a — session-surface resolution through public boundary
    "ResolvedSessionSurface",
    "SurfaceHint",
    "resolve_session_surface",
    # Surfaces
    "operate_provider_surface",
    "operate_provider_surfaces",
    # Language servers
    "LanguageServerEntry",
    # Typed family contracts callers must construct to call the API below.
    # Exported because a family function is unusable without its Request type;
    # requesters must not reach into providers.contracts.* to get them.
    "LanguageServerProjectionRequest",
    "ManagedMcpEntry",
    "ManagedMcpRequest",
    "ManagedMcpResult",
    "SelfProvidedLspRequest",
    "manage_language_servers",
    "manage_language_servers_all",
    "adopt_legacy_mcp_ownership",
    "manage_mcp_entries",
    "manage_mcp_entries_all",
    # Managed hooks
    "ManagedHooksEntry",
    "ManagedHooksRequest",
    "ManagedHooksResult",
    "manage_hook_entries",
    # Provider plugins
    "PluginEntryRequest",
    "PluginEntryResult",
    "manage_plugin_entry",
    # Model projection
    "ModelProjectionEntry",
    "ModelProjectionRequest",
    "ModelProjectionResult",
    "manage_model_projection",
    # Self-provided LSP
    "manage_self_provided_lsp",
    "manage_self_provided_lsp_all",
    # AS19 Stage-2 Slice A: harness status observer resolution
    "HarnessStatusObserverCapability",
    "open_harness_status_observer",
    "close_harness_status_observer",
    "normalize_harness_status_observation",
]
