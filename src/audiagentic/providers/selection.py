"""Provider selection and capability matching."""
from __future__ import annotations

from typing import Any

from audiagentic.contracts.errors import AudiaGenticError
from audiagentic.providers.models import resolve_model_selection
from audiagentic.providers.health import health_check


def select_provider(
    job_record: dict[str, Any],
    provider_registry: dict[str, dict[str, Any]],
    provider_config: dict[str, dict[str, Any]],
    provider_catalogs: dict[str, dict[str, Any]] | None = None,
    *,
    default_provider_id: str | None = None,
) -> str:
    provider_id = job_record.get("provider-id") or default_provider_id
    if not provider_id:
        raise AudiaGenticError(
            code="PRV-VALIDATION-002",
            kind="validation",
            message="provider-id is required",
            details={},
        )
    descriptor = provider_registry.get(provider_id)
    if descriptor is None:
        raise AudiaGenticError(
            code="PRV-VALIDATION-003",
            kind="validation",
            message="unknown provider-id",
            details={"provider-id": provider_id},
        )
    if not descriptor.get("supports-jobs", False):
        raise AudiaGenticError(
            code="PRV-VALIDATION-004",
            kind="validation",
            message="provider does not support jobs",
            details={"provider-id": provider_id},
        )
    config = provider_config.get(provider_id, {})
    result = health_check(provider_id, descriptor, config)
    if result.get("status") != "healthy" or not result.get("configured", False):
        raise AudiaGenticError(
            code="PRV-BUSINESS-002",
            kind="business-rule",
            message="provider is not healthy",
            details={"provider-id": provider_id, "status": result.get("status")},
        )
    if provider_catalogs is not None:
        resolve_model_selection(
            provider_id=provider_id,
            provider_config=config,
            job_request=job_record,
            catalog=provider_catalogs.get(provider_id),
        )
    return provider_id
