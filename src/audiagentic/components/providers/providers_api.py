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
)
from audiagentic.components.providers.contracts.generated_surface import (
    GeneratedSurfaceMode,
    GeneratedSurfaceRequest,
    GeneratedSurfaceResult,
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
from audiagentic.components.providers.contracts.model_projection import (
    ModelProjectionMode,
    ModelProjectionRequest,
    ModelProjectionResult,
)
from audiagentic.components.providers.contracts.plugin_entry import (
    PluginEntryMode,
    PluginEntryRequest,
    PluginEntryResult,
)
from audiagentic.components.providers.contracts.self_provided_lsp import (
    SelfProvidedLspMode,
    SelfProvidedLspRequest,
    SelfProvidedLspResult,
)


def manage_plugin_entry(
    project_root: Path, provider_id: str, *, mode: PluginEntryMode, request: PluginEntryRequest,
) -> PluginEntryResult:
    """Manage one generic provider plugin-config entry."""
    from audiagentic.components.providers.services.plugin_entries import (
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
    from audiagentic.components.providers.services.managed_mcp_family import (
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
    from audiagentic.components.providers.services.managed_mcp_family import (
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
    from audiagentic.components.providers.services.managed_hooks_family import (
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
    from audiagentic.components.providers.services.language_server_family import (
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
    from audiagentic.components.providers.services.automation_registry import (
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
    from audiagentic.components.providers.services.automation_registry import (
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
    from audiagentic.components.providers.services.feature_resolution import (
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
        results.append(
            manage_self_provided_lsp(project_root, pid, mode=mode, request=request)
        )
    return results


def operate_provider_surface(
    project_root: Path,
    provider_id: str,
    *,
    mode: GeneratedSurfaceMode,
    request: GeneratedSurfaceRequest,
) -> GeneratedSurfaceResult:
    """Operate on generated provider surfaces through the recipe family."""
    from audiagentic.components.providers.services.automation_registry import (
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
        single = operate_provider_surfaces(
            project_root,
            provider_id=pid,
            mode=mode,
        )
        if isinstance(single, GeneratedSurfaceResult):
            results.append(single)
    return results


def list_providers(project_root: Path) -> dict[str, Any]:
    from audiagentic.components.providers.services.status import build_provider_status
    return build_provider_status(project_root, include_probes=False)


def get_provider_status(project_root: Path, provider_id: str) -> dict[str, Any]:
    from audiagentic.components.providers.services.status import build_provider_status
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
                {"rel_path": agent_file.rel_path, "managed": agent_file.managed, "description": agent_file.description}
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
    from audiagentic.components.providers.services.provider_catalog import (
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
    from audiagentic.components.providers.services.catalog import fetch_provider_catalog

    try:
        return await asyncio.to_thread(fetch_provider_catalog, provider_id, project_root=project_root)
    except Exception as exc:  # noqa: BLE001
        return {"provider_id": provider_id, "ok": False, "error": str(exc)}


# --- provider interrogation (MO11) --------------------------------------------


def _serialize_config_surface(kind: str, spec, project_root: Path) -> dict[str, Any]:
    """Serialize one managed-config surface: {kind, configured, path_scope,
    resolved_path, format, refresh_mode, capabilities} — never callable reprs
    or secret refs (MO11 step 3). Home prefixes redact to ``~``."""
    if spec is None:
        return {"kind": kind, "configured": False}
    from audiagentic.foundation.toolchains.managed_config import (
        resolve_managed_config_path,
    )

    entry: dict[str, Any] = {
        "kind": kind,
        "configured": True,
        "format": spec.format,
        "refresh_mode": spec.refresh_mode,
        "capabilities": sorted(spec.capabilities),
        "resolved_path": None,
        "path_scope": None,
    }
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
        entry["path_scope"] = "project" if not resolved.is_absolute() or str(resolved).startswith(str(project_root)) else "absolute"
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
    discovery, NO duplicate probes/catalog parsing, and NO agent-profile join
    (agents owns profiles — ``related_tools`` points there instead).
    """
    from audiagentic.components.providers.descriptors.registry import get_descriptor
    from audiagentic.components.providers.services.execution import (
        describe_execution_support,
    )
    from audiagentic.components.providers.services.managed_mcp_registry import (
        mcp_ownership_registry,
    )
    from audiagentic.components.providers.services.models import (
        model_ownership_registry,
    )

    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return {"provider_id": provider_id, "ok": False, "reason": "unknown-provider"}

    summary_rows = [
        row for row in list_provider_descriptors() if row["provider_id"] == provider_id
    ]
    return {
        "provider_id": provider_id,
        "ok": True,
        "descriptor": summary_rows[0] if summary_rows else {},
        "status": get_provider_status(project_root, provider_id),
        "execution": describe_execution_support(provider_id),
        "models": list_provider_models(project_root, provider_id),
        "models_config": list_provider_models_config(project_root, provider_id),
        "config_surfaces": [
            _serialize_config_surface("mcp", descriptor.mcp_config, project_root),
            _serialize_config_surface(
                "language-servers", descriptor.language_servers_config, project_root
            ),
            _serialize_config_surface("model-endpoints", descriptor.model_config, project_root),
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
        "vendor_key_injection": {
            vendor: {"mechanism": spec.get("mechanism"), "key": spec.get("key")}
            for vendor, spec in descriptor.vendor_key_injection.items()
        },
        "related_tools": ["agent_list_profiles"],
    }


# --- model-source management (MO02 step 9/11) --------------------------------
#
# Mutation semantics (step 11): dry_run=True validates + computes the diff but
# writes NOTHING (neither model-sources.yaml, ownership registry, nor provider
# config); apply=False atomically writes desired state only; apply=True writes
# desired state then reconciles provider configs. If reconcile fails, desired
# state remains committed and the result reports applied=False + action_needed
# — never a false rollback claim. Tools mutate DESIRED STATE only; provider
# config files are written exclusively by the reconcile/sync path.


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
    *,
    apply: bool,
    dry_run: bool,
) -> dict[str, Any]:
    from audiagentic.components.providers.services.model_source_config import (
        load_model_sources,
        validate_model_sources,
        write_model_sources,
    )
    from audiagentic.components.providers.services.models import (
        record_model_config_timeline,
        sync_all_provider_models,
    )
    from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

    current = load_model_sources(project_root)
    proposed = mutate(json_roundtrip(current))
    issues = validate_model_sources(proposed)
    if issues:
        raise make_error(
            prefix="VAL", component="MEP", number=1, kind="providers",
            message="model-sources.yaml failed schema validation",
            details={"issues": issues},
        )

    diff = _model_source_diff(current, proposed)
    result: dict[str, Any] = {"ok": True, "diff": diff, "dry_run": dry_run, "applied": False}
    if dry_run:
        return result

    write_model_sources(project_root, proposed)
    result["written"] = True
    for source_id in diff["added"] + diff["changed"] + diff["removed"]:
        record_model_config_timeline(
            project_root, "model-sources", "model-config.planned",
            attributes={"source-id": source_id},
        )
    if not apply:
        return result

    try:
        sync_result = sync_all_provider_models(project_root)
    except AudiaGenticError as exc:
        result["applied"] = False
        result["action_needed"] = (
            f"desired state written but reconcile failed ({exc.code}); "
            "run sync_provider_models per provider to apply"
        )
        return result
    result["sync"] = sync_result
    result["applied"] = bool(sync_result.get("ok"))
    if not result["applied"]:
        result["action_needed"] = (
            "desired state written but one or more provider syncs failed; "
            "see sync.providers for details"
        )
    return result


def json_roundtrip(value: dict[str, Any]) -> dict[str, Any]:
    import copy

    return copy.deepcopy(value)


def model_source_list(project_root: Path) -> dict[str, Any]:
    from audiagentic.components.providers.services.model_source_config import (
        load_model_sources,
    )

    document = load_model_sources(project_root)
    sources = {
        source_id: {
            "source-class": source.get("source-class"),
            "display-name": source.get("display-name"),
            "connector": source.get("connector"),
            "model-discovery": source.get("model-discovery"),
            "model-id": source.get("model-id"),
            "enabled": source.get("enabled", True),
            "api-key-ref": source.get("api-key-ref"),
        }
        for source_id, source in (document.get("sources") or {}).items()
    }
    return {"ok": True, "contract-version": document.get("contract-version"), "sources": sources}


def model_source_add(
    project_root: Path,
    source_id: str,
    config: dict[str, Any],
    *,
    apply: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    from audiagentic.foundation.contracts.errors import make_error

    def mutate(document: dict[str, Any]) -> dict[str, Any]:
        sources = document.setdefault("sources", {})
        if source_id in sources:
            raise make_error(
                prefix="VAL", component="MEP", number=1, kind="providers",
                message="model source already exists; use model_source_update",
                details={"source-id": source_id},
            )
        sources[source_id] = config
        return document

    return _mutate_model_sources(project_root, mutate, apply=apply, dry_run=dry_run)


def _require_source(document: dict[str, Any], source_id: str) -> dict[str, Any]:
    from audiagentic.foundation.contracts.errors import make_error

    sources = document.get("sources") or {}
    if source_id not in sources:
        raise make_error(
            prefix="VAL", component="MEP", number=1, kind="providers",
            message="unknown model source id",
            details={"source-id": source_id},
        )
    return sources


def model_source_update(
    project_root: Path,
    source_id: str,
    updates: dict[str, Any],
    *,
    apply: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    def mutate(document: dict[str, Any]) -> dict[str, Any]:
        sources = _require_source(document, source_id)
        sources[source_id].update(updates)
        return document

    return _mutate_model_sources(project_root, mutate, apply=apply, dry_run=dry_run)


def model_source_remove(
    project_root: Path,
    source_id: str,
    *,
    apply: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    def mutate(document: dict[str, Any]) -> dict[str, Any]:
        sources = _require_source(document, source_id)
        del sources[source_id]
        return document

    return _mutate_model_sources(project_root, mutate, apply=apply, dry_run=dry_run)


def model_source_set_enabled(
    project_root: Path,
    source_id: str,
    enabled: bool,
    *,
    apply: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    def mutate(document: dict[str, Any]) -> dict[str, Any]:
        sources = _require_source(document, source_id)
        sources[source_id]["enabled"] = enabled
        return document

    return _mutate_model_sources(project_root, mutate, apply=apply, dry_run=dry_run)


def sync_provider_models(
    project_root: Path, provider_id: str, *, dry_run: bool = False
) -> dict[str, Any]:
    from audiagentic.components.providers.services.feature_resolution import (
        enabled_provider_ids,
    )
    from audiagentic.components.providers.services.model_source_config import (
        load_model_sources,
    )
    from audiagentic.components.providers.services.models import (
        materialize_local_endpoint_sources,
        sync_managed_provider_models,
    )

    enabled = provider_id in enabled_provider_ids(project_root)
    entries = (
        materialize_local_endpoint_sources(load_model_sources(project_root))
        if enabled
        else []
    )
    if dry_run:
        return {
            "provider_id": provider_id,
            "ok": True,
            "dry_run": True,
            "provider_enabled": enabled,
            "desired_managed_ids": sorted(entry.managed_id for entry in entries),
        }
    return sync_managed_provider_models(provider_id, project_root, entries)


def list_provider_models_config(project_root: Path, provider_id: str) -> dict[str, Any]:
    from audiagentic.components.providers.services.models import (
        list_provider_models_config as _list,
    )

    return _list(provider_id, project_root)


def reload_provider_models(project_root: Path, provider_id: str) -> dict[str, Any]:
    from audiagentic.components.providers.services.models import (
        reload_provider_models as _reload,
    )

    return _reload(provider_id, project_root)


async def refresh_all_catalogs(project_root: Path) -> dict[str, Any]:
    from audiagentic.components.providers.services.catalog import (
        refresh_all_catalogs as _refresh,
    )

    return await asyncio.to_thread(_refresh, project_root=project_root)


async def manage_cli_lifecycle(
    project_root: Path, provider_id: str, *, mode: CliLifecycleMode
) -> dict[str, Any]:
    from audiagentic.components.providers.services.automation_registry import (
        build_automation_registry,
    )

    registry = build_automation_registry(project_root)
    result = registry.dispatch(
        provider_id,
        "cli-lifecycle",
        mode,
        CliLifecycleRequest(),
    )
    from audiagentic.components.providers.contracts.cli_lifecycle import CliLifecycleResult

    if isinstance(result, CliLifecycleResult):
        return result.to_mapping()
    if isinstance(result, dict):
        return result
    return {"ok": False, "supported": False, "state": "failed"}


async def reconcile_provider(project_root: Path, provider_id: str, *, fetch_catalog: bool) -> dict[str, Any]:
    from audiagentic.components.providers.services.lifecycle import (
        reconcile_provider as _reconcile,
    )

    return await asyncio.to_thread(
        _reconcile, provider_id, project_root=project_root, fetch_catalog=fetch_catalog
    )


async def reconcile_all_providers(project_root: Path, *, fetch_catalogs: bool) -> dict[str, Any]:
    from audiagentic.components.providers.services.lifecycle import (
        reconcile_all_providers as _reconcile_all,
    )

    return await asyncio.to_thread(
        _reconcile_all, project_root=project_root, fetch_catalogs=fetch_catalogs
    )


__all__ = [
    "list_providers",
    "get_provider_status",
    "list_provider_descriptors",
    "list_provider_models",
    "refresh_provider_catalog",
    "describe_provider",
    # Model source management (MO02)
    "model_source_list",
    "model_source_add",
    "model_source_update",
    "model_source_remove",
    "model_source_set_enabled",
    "sync_provider_models",
    "list_provider_models_config",
    "reload_provider_models",
    "refresh_all_catalogs",
    # Provider lifecycle
    "manage_cli_lifecycle",
    "reconcile_provider",
    "reconcile_all_providers",
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
    "SelfProvidedLspRequest",
    "manage_language_servers",
    "manage_language_servers_all",
    "adopt_legacy_mcp_ownership",
    "manage_mcp_entries",
    "manage_mcp_entries_all",
    # Managed hooks
    "ManagedHooksEntry",
    "ManagedHooksRequest",
    "manage_hook_entries",
    # Model projection
    "manage_model_projection",
    # Self-provided LSP
    "manage_self_provided_lsp",
    "manage_self_provided_lsp_all",
]
