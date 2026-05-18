"""Provider model catalog fetching."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.config.provider_catalog import build_model_catalog, write_model_catalog
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.interoperability.providers.descriptors.registry import all_descriptors


def fetch_provider_catalog(
    provider_id: str,
    *,
    project_root: Path,
    provider_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    descriptors = all_descriptors()
    desc = descriptors.get(provider_id)
    if desc is None:
        raise AudiaGenticError(
            code="PRV-CATALOG-001",
            kind="not-found",
            message=f"no descriptor for provider {provider_id!r}",
            details={"provider-id": provider_id},
        )
    if desc.fetch_catalog_fn is None:
        raise AudiaGenticError(
            code="PRV-CATALOG-002",
            kind="not-supported",
            message=f"provider {provider_id!r} does not support catalog fetch",
            details={"provider-id": provider_id},
        )
    models = desc.fetch_catalog_fn(provider_config or {})
    if not models:
        raise AudiaGenticError(
            code="PRV-CATALOG-003",
            kind="empty",
            message=f"catalog fetch returned no models for {provider_id!r}",
            details={"provider-id": provider_id},
        )
    payload = build_model_catalog(provider_id=provider_id, models=models, source="cli")
    path = write_model_catalog(project_root, payload)
    return {"provider_id": provider_id, "model_count": len(models), "path": str(path), "ok": True}


def refresh_all_catalogs(*, project_root: Path) -> dict[str, Any]:
    results = []
    for provider_id, desc in sorted(all_descriptors().items()):
        if desc.fetch_catalog_fn is None:
            continue
        try:
            result = fetch_provider_catalog(provider_id, project_root=project_root)
        except Exception as exc:  # noqa: BLE001
            result = {"provider_id": provider_id, "ok": False, "error": str(exc)}
        results.append(result)
    return {"ok": all(r.get("ok") for r in results), "providers": results}
