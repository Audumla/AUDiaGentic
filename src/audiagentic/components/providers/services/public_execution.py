"""Provider-owned implementation behind the public one-shot execution seam."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.provider_execution import (
    ProviderAcpLaunchResult,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    ProviderIsolationTier,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


def get_provider_execution_isolation_tier(provider_id: str) -> ProviderIsolationTier:
    """Return the descriptor-backed provider-wide execution isolation fact."""
    from audiagentic.components.providers.descriptors.registry import get_descriptor

    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        raise AudiaGenticError(
            code="RES-PEXE-001",
            kind="providers",
            message="provider descriptor is required for execution",
            details={"provider-id": provider_id},
        )
    return descriptor.execution_isolation_tier


def get_provider_runtime_config_state(
    project_root: Path,
    provider_id: str,
) -> dict[str, Any]:
    """Return the provider-owned state that affects one provider runtime.

    This query is intentionally provider-scoped: gateway fingerprinting does
    not need unrelated provider configuration and must not read provider
    internals directly.
    """
    from audiagentic.components.providers.services.provider_config import (
        is_provider_enabled,
        load_provider_config,
    )

    document = load_provider_config(project_root)
    configured = (document.get("providers") or {}).get(provider_id, {})
    return {
        "provider-id": provider_id,
        "enabled": is_provider_enabled(project_root, provider_id),
        "config": dict(configured) if isinstance(configured, dict) else configured,
    }


def execute_provider_turn(request: ProviderExecutionRequest) -> ProviderExecutionResult:
    """Resolve and execute one provider turn inside its assigned worker."""
    from audiagentic.components.providers.services.execution import execute_provider
    from audiagentic.components.providers.services.models import resolve_model_selection

    runtime = get_provider_runtime_config_state(request.project_root, request.provider_id)
    if not runtime["enabled"]:
        raise AudiaGenticError(
            code="CFG-PEXE-001",
            kind="providers",
            message="provider is disabled for execution",
            details={"provider-id": request.provider_id},
        )

    declared_tier = get_provider_execution_isolation_tier(request.provider_id)
    if declared_tier != request.provider_isolation_tier:
        raise AudiaGenticError(
            code="CON-PEXE-001",
            kind="providers",
            message="provider execution isolation tier does not match descriptor",
            details={
                "provider-id": request.provider_id,
                "requested": request.provider_isolation_tier,
                "declared": declared_tier,
            },
        )

    provider_config = runtime["config"]
    if not isinstance(provider_config, dict):
        provider_config = {}
    model = resolve_model_selection(
        provider_id=request.provider_id,
        provider_config=provider_config,
        job_request={
            "model-id": request.model_id,
            "model-alias": request.model_alias,
        },
    )
    model_id = str(model["model-id"])
    packet_data = dict(request.packet_data)
    packet_data.update(
        {
            "working-root": str(request.project_root),
            "provider-id": request.provider_id,
            "model-id": model_id,
            "model-alias": request.model_alias,
        }
    )
    result = execute_provider(
        provider_id=request.provider_id,
        packet_ctx=packet_data,
        provider_cfg=provider_config,
    )
    return ProviderExecutionResult(
        provider_id=request.provider_id,
        model_id=str(result.get("model") or model_id),
        worker_id=request.worker_id,
        attempt_epoch=request.attempt_epoch,
        result_data=result,
    )


def prepare_provider_execution_environment(
    request: ProviderExecutionRequest,
) -> dict[str, str]:
    """Materialize transient provider-owned environment before HOME isolation."""
    from audiagentic.components.providers.services.execution import (
        load_execution_environment_builder,
    )
    from audiagentic.components.providers.services.models import resolve_model_selection

    runtime = get_provider_runtime_config_state(request.project_root, request.provider_id)
    provider_config = runtime["config"] if isinstance(runtime["config"], dict) else {}
    model = resolve_model_selection(
        provider_id=request.provider_id,
        provider_config=provider_config,
        job_request={"model-id": request.model_id, "model-alias": request.model_alias},
    )
    builder = load_execution_environment_builder(request.provider_id)
    if builder is None:
        return {}
    result = builder(model_id=str(model["model-id"]))
    if not isinstance(result, dict) or not all(
        isinstance(name, str) and isinstance(value, str)
        for name, value in result.items()
    ):
        raise AudiaGenticError(
            code="INT-PEXE-003",
            kind="providers",
            message="provider execution environment builder returned an invalid mapping",
        )
    return result


def prepare_provider_acp_launch(
    project_root: Path,
    *,
    provider_id: str,
    model_id: str | None,
    model_alias: str | None,
) -> ProviderAcpLaunchResult:
    """Resolve one provider-owned ACP launch without exposing adapter internals."""
    from audiagentic.components.providers.services.execution import load_acp_launch_builder
    from audiagentic.components.providers.services.models import resolve_model_selection

    runtime = get_provider_runtime_config_state(project_root, provider_id)
    if not runtime["enabled"]:
        raise AudiaGenticError(
            code="CFG-PEXE-001",
            kind="providers",
            message="provider is disabled for execution",
            details={"provider-id": provider_id},
        )
    builder = load_acp_launch_builder(provider_id)
    if builder is None:
        raise AudiaGenticError(
            code="UNS-PEXE-002",
            kind="providers",
            message="provider does not support ACP live sessions",
            details={"provider-id": provider_id},
        )
    provider_config = runtime["config"]
    if not isinstance(provider_config, dict):
        provider_config = {}
    model = resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_config,
        job_request={"model-id": model_id, "model-alias": model_alias},
    )
    resolved_model_id = str(model.get("model-id") or model.get("resolved") or "")
    if not resolved_model_id:
        raise AudiaGenticError(
            code="INT-PEXE-001",
            kind="providers",
            message="provider ACP launch did not resolve a model identifier",
            details={"provider-id": provider_id},
        )
    return ProviderAcpLaunchResult(
        provider_id=provider_id,
        model_id=resolved_model_id,
        launch=builder(project_root, model_id=resolved_model_id),
    )


__all__ = [
    "execute_provider_turn",
    "get_provider_execution_isolation_tier",
    "get_provider_runtime_config_state",
    "prepare_provider_execution_environment",
    "prepare_provider_acp_launch",
]
