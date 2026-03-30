"""Provider model selection helpers."""
from __future__ import annotations

from typing import Any

from audiagentic.contracts.errors import AudiaGenticError

from audiagentic.providers.catalog import catalog_is_stale, catalog_model_ids


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
                code="PRV-VALIDATION-005",
                kind="validation",
                message="unknown model alias",
                details={"provider-id": provider_id, "model-alias": model_alias},
            )
    elif default_model:
        resolved = default_model
        resolved_from = "default"
    else:
        raise AudiaGenticError(
            code="PRV-VALIDATION-006",
            kind="validation",
            message="model-id or model-alias is required",
            details={"provider-id": provider_id},
        )

    if catalog is not None:
        allowed = catalog_model_ids(catalog)
        if resolved not in allowed:
            raise AudiaGenticError(
                code="PRV-BUSINESS-003",
                kind="business-rule",
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
