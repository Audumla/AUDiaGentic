"""Provider model selection + managed model-endpoint sync (MO02).

The sync half binds the model-endpoints managed-config kind onto the shared
MO06 core: this module builds provider-NEUTRAL desired entries from
model-sources and hands them to ``sync_managed_config`` with the provider's
``model_config`` spec. It never imports adapter modules and never branches on
``provider_id`` or connector names — provider-native payload shapes come from
the adapter-owned ``model_entry_renderer`` callable each provider's YAML
declares as a dotted ref (resolved at descriptor load, same pattern as
reader/writer/remover — RV271).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.components.providers.services.provider_catalog import (
    catalog_is_stale,
    catalog_model_ids,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error_factory
from audiagentic.foundation.toolchains.managed_config import (
    ManagedFragmentRegistry,
    reload_managed_config,
    resolve_managed_config_path,
    sync_managed_config,
)

_model_error = make_error_factory("VAL", "MEP", "providers")


@dataclass(frozen=True)
class MaterializedModelEntry:
    """Provider-neutral materialized model entry (MO02 step 10).

    Contains NO provider-native container/key/casing — adapter renderers
    convert it to the payload each provider's ``model_config.writer`` accepts.
    ``managed_id`` follows MO01 step 6: ``model-endpoints/<source-id>`` for
    local-endpoint sources; ``model-endpoints/<source-id>/<model-id>`` for
    remote-account custom-entries (MO07).
    """

    source_id: str
    model_id: str
    visible_name: str
    connector: str
    managed_id: str
    endpoint: dict[str, Any] = field(default_factory=dict)  # base-url, connector-options
    capabilities: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)  # context-window, max-output-tokens
    auth_ref: str | None = None


def materialize_local_endpoint_sources(document: dict[str, Any]) -> list[MaterializedModelEntry]:
    """Materialize enabled ``local-endpoint`` sources from a model-sources doc.

    1:1 — each enabled local-endpoint source yields exactly one entry with
    managed id ``model-endpoints/<source-id>``. remote-account sources are
    materialized by MO07 through the same entry type, not here.
    """
    entries: list[MaterializedModelEntry] = []
    for source_id, source in (document.get("sources") or {}).items():
        if source.get("source-class") != "local-endpoint":
            continue
        if source.get("enabled", True) is False:
            continue
        endpoint: dict[str, Any] = {"single-model": True}
        if source.get("base-url"):
            endpoint["base-url"] = source["base-url"]
        if source.get("connector-options"):
            endpoint["connector-options"] = dict(source["connector-options"])
        if source.get("provider-overrides"):
            endpoint["provider-overrides"] = dict(source["provider-overrides"])
        limits: dict[str, Any] = {}
        if source.get("context-window"):
            limits["context-window"] = source["context-window"]
        if source.get("max-output-tokens"):
            limits["max-output-tokens"] = source["max-output-tokens"]
        entries.append(
            MaterializedModelEntry(
                source_id=source_id,
                model_id=source["model-id"],
                visible_name=source.get("display-name", source["model-id"]),
                connector=source["connector"],
                managed_id=f"model-endpoints/{source_id}",
                endpoint=endpoint,
                capabilities=dict(source.get("capabilities") or {}),
                limits=limits,
                auth_ref=source.get("api-key-ref"),
            )
        )
    return entries


def _model_config_timeline_path(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "providers" / "model-config-timeline.jsonl"


def record_model_config_timeline(
    project_root: Path,
    provider_id: str,
    event: str,
    *,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Append one model-config timeline event (MO02 step 13).

    Identity: component=providers, resource-kind=provider-model-config,
    resource-id=<provider-id>, event=model-config.{planned|updated|removed|
    collision|reload-required}. Attributes carry counts/managed ids only —
    never payloads or auth refs. Best-effort: observability must not break
    the sync. No bus topics are emitted here (RV313: BU01 has not landed;
    bare string-literal topics are never acceptable).
    """
    from audiagentic.foundation.observability import record_timeline_event

    record_timeline_event(
        _model_config_timeline_path(project_root),
        component="providers",
        resource_kind="provider-model-config",
        resource_id=provider_id,
        event=event,
        attributes=attributes or {},
    )


def model_ownership_registry(project_root: Path) -> ManagedFragmentRegistry:
    """The one model-endpoints instance of the foundation ManagedFragmentRegistry."""
    return ManagedFragmentRegistry(
        project_root,
        "managed-model-endpoints.json",
        top_level_key="providers",
    )


def _model_spec(provider_id: str):
    from audiagentic.components.providers.descriptors.registry import get_descriptor

    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        raise _model_error(4, "unknown provider for model config", provider_id=provider_id)
    return descriptor, descriptor.model_config


def _build_desired_entries(
    provider_id: str,
    descriptor: Any,
    entries: list[MaterializedModelEntry],
) -> tuple[dict[str, tuple[str, Any]], list[dict[str, str]]]:
    """Render neutral entries into (managed_id -> (name, native payload)).

    The renderer is the adapter-owned callable declared in provider YAML
    (``model_entry_renderer`` dotted ref, resolved at descriptor load) — the
    same declaration pattern as reader/writer/remover, not a runtime lookup.
    Entries whose connector the provider does not declare are SKIPPED (an
    undeclared pair projects nothing — MO01 step 4), reported so status can
    surface them; they are never silently dropped nor an error for
    full-provider sync.
    """
    renderer = descriptor.model_entry_renderer
    if renderer is None:
        raise _model_error(
            2,
            "provider declares model_config but no model_entry_renderer",
            provider_id=provider_id,
        )

    supported = set(descriptor.supported_connectors)
    desired: dict[str, tuple[str, Any]] = {}
    skipped: list[dict[str, str]] = []
    for entry in entries:
        if entry.connector not in supported:
            skipped.append({
                "managed_id": entry.managed_id,
                "connector": entry.connector,
                "reason": "connector not declared in provider supported_connectors",
            })
            continue
        name, payload = renderer(entry)
        desired[entry.managed_id] = (name, payload)
    return desired, skipped


def sync_managed_provider_models(
    provider_id: str,
    project_root: Path,
    entries: list[MaterializedModelEntry],
    *,
    managed_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Sync AUDiaGentic-owned model entries for one provider.

    Thin binding over the shared ``sync_managed_config`` core (MO06) — no
    reimplementation of the reconcile loop. An empty *entries* list prunes
    all owned model entries (disabled-provider semantics, MO02 step 12).
    """
    descriptor, spec = _model_spec(provider_id)
    if spec is None:
        return {"provider_id": provider_id, "ok": True, "skipped": "no model_config defined"}

    desired, skipped_connectors = _build_desired_entries(provider_id, descriptor, entries)
    result = sync_managed_config(
        spec,
        project_root,
        provider_id,
        desired,
        registry=model_ownership_registry(project_root),
        managed_ids=managed_ids,
    ).to_dict()
    if skipped_connectors:
        result["skipped_connectors"] = skipped_connectors

    if result.get("updated"):
        record_model_config_timeline(
            project_root, provider_id, "model-config.updated",
            attributes={"count": len(result["updated"]), "names": result["updated"]},
        )
    if result.get("removed"):
        record_model_config_timeline(
            project_root, provider_id, "model-config.removed",
            attributes={"count": len(result["removed"]), "names": result["removed"]},
        )
    if result.get("collisions"):
        record_model_config_timeline(
            project_root, provider_id, "model-config.collision",
            attributes={"count": len(result["collisions"]), "collisions": result["collisions"]},
        )
    if result.get("method") == "restart-required":
        record_model_config_timeline(
            project_root, provider_id, "model-config.reload-required", attributes={}
        )
    return result


def sync_managed_provider_models_subset(
    provider_id: str,
    project_root: Path,
    entries: list[MaterializedModelEntry],
    *,
    managed_ids: set[str],
) -> dict[str, Any]:
    """Sync only selected managed model entries for one provider."""
    return sync_managed_provider_models(
        provider_id, project_root, entries, managed_ids=managed_ids
    )


def sync_all_provider_models(project_root: Path) -> dict[str, Any]:
    """Sync managed model entries for every model-config-capable provider.

    MO02 step 12 branch semantics: enabled providers receive the desired set
    materialized from model-sources; disabled providers receive an empty set
    so owned entries are pruned. Providers without model_config are skipped
    inside the wrapper. Per-provider failures are reported, not raised — one
    broken provider config must not abort the rest.
    """
    from audiagentic.components.providers.descriptors.registry import all_descriptors
    from audiagentic.components.providers.services.feature_resolution import (
        enabled_provider_ids,
    )
    from audiagentic.components.providers.services.model_source_config import (
        load_model_sources,
    )

    entries = materialize_local_endpoint_sources(load_model_sources(project_root))
    enabled = enabled_provider_ids(project_root)
    results: dict[str, dict[str, Any]] = {}
    ok = True
    for provider_id, descriptor in sorted(all_descriptors().items()):
        if descriptor.model_config is None:
            continue
        desired = entries if provider_id in enabled else []
        try:
            result = sync_managed_provider_models(provider_id, project_root, desired)
        except AudiaGenticError as exc:
            result = {"provider_id": provider_id, "ok": False, "error_code": exc.code}
        results[provider_id] = result
        ok = ok and bool(result.get("ok", True))
    return {"ok": ok, "providers": results}


def list_provider_models_config(provider_id: str, project_root: Path) -> dict[str, Any]:
    """Read the MANAGED model-config view for one provider.

    Distinct from the runtime-catalog read (``list_provider_models``): this
    reports what AUDiaGentic has materialized into the provider's config plus
    the ownership registry entries, not what the tool says it can run.
    """
    descriptor, spec = _model_spec(provider_id)
    if spec is None:
        return {
            "provider_id": provider_id,
            "ok": True,
            "supported": False,
            "entries": [],
            "managed": {},
        }
    config_path = resolve_managed_config_path(spec, project_root)
    try:
        current = spec.reader(config_path)
    except Exception as exc:  # noqa: BLE001 — read failure is a report, not a crash
        return {
            "provider_id": provider_id,
            "ok": False,
            "supported": True,
            "config_path": str(config_path),
            "error": str(exc),
        }
    owned = model_ownership_registry(project_root).load().get(provider_id, {})
    return {
        "provider_id": provider_id,
        "ok": True,
        "supported": True,
        "config_path": str(config_path),
        "format": spec.format,
        "refresh_mode": spec.refresh_mode,
        "entries": sorted(current),
        "managed": dict(owned),
    }


def reload_provider_models(provider_id: str, project_root: Path) -> dict[str, Any]:
    """Refresh-mode-aware reload (or action-needed text) for model config."""
    descriptor, spec = _model_spec(provider_id)
    if spec is None:
        return {"provider_id": provider_id, "ok": False, "error": "no model_config defined"}
    result = reload_managed_config(spec, project_root, display_name=descriptor.display_name)
    result["provider_id"] = provider_id
    return result


def resolve_model_selection(
    *,
    provider_id: str,
    provider_config: dict[str, Any],
    job_request: dict[str, Any],
    catalog: dict[str, Any] | None = None,
    now_fn=None,
) -> dict[str, Any]:
    model_id = job_request.get("model-id")
    model_alias = job_request.get("model-alias")
    default_model = job_request.get("default-model") or provider_config.get("default-model")
    aliases = provider_config.get("model-aliases", {})
    resolved_from = "explicit-id"

    if model_id:
        resolved = model_id
    elif model_alias:
        resolved = aliases.get(model_alias)
        resolved_from = "alias"
        if resolved is None:
            raise AudiaGenticError(
                code="VAL-MODEL-001",
                kind="providers",
                message="unknown model alias",
                details={"provider-id": provider_id, "model-alias": model_alias},
            )
    elif default_model:
        resolved = default_model
        resolved_from = "default"
    else:
        raise AudiaGenticError(
            code="VAL-MODEL-002",
            kind="providers",
            message="model-id or model-alias is required",
            details={"provider-id": provider_id},
        )

    if catalog is not None:
        allowed = catalog_model_ids(catalog)
        if resolved not in allowed:
            raise AudiaGenticError(
                code="CON-MODEL-001",
                kind="providers",
                message="resolved model is not in provider catalog",
                details={"provider-id": provider_id, "model-id": resolved},
            )

    result = {
        "provider-id": provider_id,
        "model-id": resolved,
        "model-alias": model_alias,
        "default-model": default_model,
        "resolved-from": resolved_from,
    }
    if catalog is not None and "catalog-refresh" in provider_config:
        refresh = provider_config.get("catalog-refresh", {})
        max_age = refresh.get("max-age-hours")
        if isinstance(max_age, int) and max_age > 0 and catalog_is_stale(catalog, max_age_hours=max_age, now_fn=now_fn):
            result["catalog-warning"] = "catalog is stale"
    return result
