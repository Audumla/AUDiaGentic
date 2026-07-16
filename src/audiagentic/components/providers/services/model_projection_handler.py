"""Per-provider model-projection handler (Pattern A — explicit code registration)."""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.model_projection import (
    ModelProjectionMode,
    ModelProjectionRequest,
    ModelProjectionResult,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.models import (
    MaterializedModelEntry,
    _build_desired_entries,
    sync_managed_provider_models,
)
from audiagentic.components.providers.services.models import (
    list_provider_models_config as _list_config,
)

_SUPPORTED_MODES = frozenset({"plan", "apply", "prune", "status"})


def _entry_to_materialized(entry) -> MaterializedModelEntry:
    """Convert contract entry to internal MaterializedModelEntry."""
    return MaterializedModelEntry(
        source_id=entry.source_id,
        model_id=entry.model_id,
        visible_name=entry.visible_name,
        connector=entry.connector,
        managed_id=entry.managed_id,
        endpoint=dict(entry.endpoint),
        capabilities=dict(entry.capabilities),
        limits=dict(entry.limits),
        auth_ref=entry.auth_ref,
    )


def _make_model_projection_handler(
    provider_id: str, project_root: Path
) -> Any:
    """Factory that binds project_root and returns a RecipeHandler-compatible closure."""
    return partial(_handler_impl, provider_id=provider_id, project_root=project_root)


def _handler_impl(
    mode: ModelProjectionMode,
    payload: object,
    ownership_scope: object | None,
    *,
    provider_id: str,
    project_root: Path,
) -> ModelProjectionResult:
    """Execute one model-projection operation for a specific provider."""
    descriptor = get_descriptor(provider_id)
    if (
        descriptor is None
        or descriptor.model_config is None
        or descriptor.automation_capability("model-projection") is None
    ):
        return ModelProjectionResult(
            ok=False, supported=False, provider_id=provider_id, error_code="RES-PREC-001"
        )
    if mode not in _SUPPORTED_MODES:
        return ModelProjectionResult(
            ok=False, supported=True, provider_id=provider_id, error_code="CON-PREC-002"
        )

    if isinstance(payload, dict):
        request = ModelProjectionRequest.from_mapping(payload)
    elif isinstance(payload, ModelProjectionRequest):
        request = payload
    else:
        return ModelProjectionResult(
            ok=False, supported=True, provider_id=provider_id, error_code="VAL-PMOD-001"
        )

    if mode == "plan":
        return _do_plan(provider_id, descriptor, request)
    if mode == "status":
        return _do_status(provider_id, project_root)
    if mode == "apply":
        return _do_apply(provider_id, project_root, request)
    # mode == "prune"
    return _do_prune(provider_id, project_root, request)


def _do_plan(
    provider_id: str,
    descriptor: Any,
    request: ModelProjectionRequest,
) -> ModelProjectionResult:
    """Compute the plan without writing anything."""
    entries = [_entry_to_materialized(e) for e in request.entries]
    desired, skipped = _build_desired_entries(provider_id, descriptor, entries)
    return ModelProjectionResult(
        ok=True,
        supported=True,
        provider_id=provider_id,
        added=tuple(sorted(desired)),
        skipped_connectors=tuple(skipped),
    )


def _do_status(
    provider_id: str,
    project_root: Path,
) -> ModelProjectionResult:
    """Return current managed model config status."""
    config = _list_config(provider_id, project_root)
    if not config.get("ok"):
        return ModelProjectionResult(
            ok=False,
            supported=True,
            provider_id=provider_id,
            error_code=config.get("error") or "CON-PMOD-001",
        )
    return ModelProjectionResult(
        ok=True,
        supported=True,
        provider_id=provider_id,
        added=tuple(sorted(config.get("entries") or [])),
        skipped_connectors=tuple(),
    )


def _do_apply(
    provider_id: str,
    project_root: Path,
    request: ModelProjectionRequest,
) -> ModelProjectionResult:
    """Apply desired model entries."""
    entries = [_entry_to_materialized(e) for e in request.entries]
    managed_ids = set(request.managed_ids) if request.managed_ids else None
    result = sync_managed_provider_models(
        provider_id, project_root, entries, managed_ids=managed_ids
    )
    collisions = result.get("collisions") or []
    return ModelProjectionResult(
        ok=bool(result.get("ok")),
        supported=True,
        provider_id=provider_id,
        added=tuple(sorted(result.get("added") or [])),
        removed=tuple(sorted(result.get("removed") or [])),
        updated=tuple(sorted(result.get("updated") or [])),
        collisions=tuple(sorted({
            str(row.get("managed_id") or row.get("managed-id") or "")
            for row in collisions
        } - {""})),
        skipped_connectors=tuple(result.get("skipped_connectors") or []),
        error_code=None if result.get("ok") else "CON-PMOD-002",
        action_needed=result.get("action_needed"),
        reload_required=result.get("method") == "restart-required",
    )


def _do_prune(
    provider_id: str,
    project_root: Path,
    request: ModelProjectionRequest,
) -> ModelProjectionResult:
    """Prune selected model entries."""
    result = sync_managed_provider_models(
        provider_id, project_root, [], managed_ids=set(request.managed_ids)
    )
    collisions = result.get("collisions") or []
    return ModelProjectionResult(
        ok=bool(result.get("ok")),
        supported=True,
        provider_id=provider_id,
        removed=tuple(sorted(result.get("removed") or [])),
        collisions=tuple(sorted({
            str(row.get("managed_id") or row.get("managed-id") or "")
            for row in collisions
        } - {""})),
        error_code=None if result.get("ok") else "CON-PMOD-003",
    )


__all__ = ["_make_model_projection_handler"]
