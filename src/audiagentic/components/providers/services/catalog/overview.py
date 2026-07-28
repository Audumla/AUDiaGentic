"""Model availability overview composition (MO20).

Composes existing reads into one coherent read-only introspection surface:
sources, their catalog freshness, models materialized per provider, and
provider execution state. No network calls — cached data only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.model_projection import (
    ModelProjectionRequest,
)
from audiagentic.components.providers.services.catalog.models import model_ownership_registry


@dataclass(frozen=True)
class SourceOverviewRow:
    """One model source in the overview."""

    source_id: str
    display_name: str | None
    enabled: bool
    connector: str
    discovery_mode: str
    filter_include: list[str] | None
    model_count: int = 0
    freshness: str = "missing"
    stale: bool = False


@dataclass(frozen=True)
class MaterializedRow:
    """One provider's managed model materialization."""

    provider_id: str
    source_id: str
    managed_id_count: int
    errors: list[str] | None = None


@dataclass(frozen=True)
class ProviderOverviewRow:
    """One provider in the overview."""

    provider_id: str
    enabled: bool
    installed: bool
    model_count: int
    models_stale: bool
    managed_model_count: int
    errors: list[str] | None = None


@dataclass(frozen=True)
class ModelAvailabilityOverview:
    """One-call cross-harness model availability overview (MO20)."""

    providers: list[ProviderOverviewRow]
    sources: list[SourceOverviewRow]
    materialized: list[MaterializedRow]

    def to_dict(self) -> dict[str, Any]:
        return {
            "providers": [
                {
                    "provider_id": row.provider_id,
                    "enabled": row.enabled,
                    "installed": row.installed,
                    "model_count": row.model_count,
                    "models_stale": row.models_stale,
                    "managed_model_count": row.managed_model_count,
                    "errors": row.errors or [],
                }
                for row in self.providers
            ],
            "sources": [
                {
                    "source_id": row.source_id,
                    "display_name": row.display_name,
                    "enabled": row.enabled,
                    "connector": row.connector,
                    "discovery_mode": row.discovery_mode,
                    "filter_include": row.filter_include,
                    "model_count": row.model_count,
                    "freshness": row.freshness,
                    "stale": row.stale,
                }
                for row in self.sources
            ],
            "materialized": [
                {
                    "provider_id": row.provider_id,
                    "source_id": row.source_id,
                    "managed_id_count": row.managed_id_count,
                    "errors": row.errors or [],
                }
                for row in self.materialized
            ],
        }


def build_model_availability_overview(project_root: Path) -> ModelAvailabilityOverview:
    """Compose the reads into one overview. Read-only, no network."""
    from audiagentic.components.providers import providers_api
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    descriptors = all_descriptors()
    provider_rows: list[ProviderOverviewRow] = []
    materialized_rows: list[MaterializedRow] = []

    # Source overview from model_source_list
    source_list = providers_api.model_source_list(project_root)
    sources_data = source_list.get("sources", {})
    source_rows: list[SourceOverviewRow] = []

    for source_id, source_cfg in sorted(sources_data.items()):
        filter_cfg = source_cfg.get("model-filter") or {}
        source_rows.append(
            SourceOverviewRow(
                source_id=source_id,
                display_name=source_cfg.get("display-name"),
                enabled=source_cfg.get("enabled", True),
                connector=source_cfg.get("connector", ""),
                discovery_mode=source_cfg.get("model-discovery", "none"),
                filter_include=filter_cfg.get("include") if filter_cfg else None,
            )
        )

    # Provider overview — one row per descriptor with model-projection capability
    ownership_registry = model_ownership_registry(project_root)
    # load() returns {provider_id: {managed_id: source_id, ...}, ...}
    owners: dict[str, dict[str, str]] = ownership_registry.load()
    entries_by_source: dict[
        str, dict[str, list[str]]
    ] = {}  # source_id -> provider_id -> [managed_ids]

    for provider_id, managed_map in owners.items():
        for managed_id, source_id in managed_map.items():
            entries_by_source.setdefault(source_id, {}).setdefault(provider_id, []).append(
                managed_id
            )

    for provider_id in sorted(descriptors.keys()):
        descriptor = descriptors[provider_id]

        # Skip providers without model-projection automation
        if descriptor.automation_capability("model-projection") is None:
            continue

        errors: list[str] = []

        # Provider status from list_providers
        status_result = providers_api.get_provider_status(project_root, provider_id)
        enabled = status_result.get("enabled", False)
        installed = status_result.get("installed", False)

        # Model count from list_provider_models (cached, no network)
        models_result = providers_api.list_provider_models(project_root, provider_id)
        model_count = len(models_result.get("models", []))
        models_stale = models_result.get("stale", False)

        # Managed model count from projection status
        try:
            proj_status = providers_api.manage_model_projection(
                project_root,
                provider_id,
                mode="status",
                request=ModelProjectionRequest(managed_ids=()),
            )
            managed_ids = [str(m) for m in (proj_status.added or [])]
        except Exception:  # noqa: BLE001 — report, don't crash
            managed_ids = []
            errors.append("model-projection status unavailable")

        # Build materialized rows per source
        for source_id in sorted(entries_by_source.keys()):
            managed = entries_by_source[source_id].get(provider_id, [])
            if managed:
                materialized_rows.append(
                    MaterializedRow(
                        provider_id=provider_id,
                        source_id=source_id,
                        managed_id_count=len(managed),
                    )
                )

        provider_rows.append(
            ProviderOverviewRow(
                provider_id=provider_id,
                enabled=bool(enabled),
                installed=bool(installed),
                model_count=model_count,
                models_stale=bool(models_stale),
                managed_model_count=len(managed_ids),
                errors=errors if errors else None,
            )
        )

    return ModelAvailabilityOverview(
        providers=provider_rows,
        sources=source_rows,
        materialized=materialized_rows,
    )
