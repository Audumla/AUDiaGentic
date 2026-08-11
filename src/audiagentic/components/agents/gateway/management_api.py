"""Generic gateway-management implementation selection and config (SH11 Slice C).

Mirrors ``components.planning.planning_api``'s generic get/set/select
pattern exactly (RV736 M2: no gateway-specific option store, second
registry, or custom validation -- these are thin wrappers over the shared
``foundation.features.*`` machinery, the same machinery `planning`,
`coding-lsp`, `memory`, and `providers` already use).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

_COMPONENT_ID = "agents"


def active_implementation_id(project_root: Path) -> str:
    """Return the enabled gateway implementation ID, or the descriptor default."""
    from audiagentic.foundation.features.registry import resolve_active_implementation

    return resolve_active_implementation(project_root, _COMPONENT_ID) or ""


def gateway_status(project_root: Path) -> dict[str, Any]:
    """Active gateway implementation and whether it was explicitly selected."""
    from audiagentic.foundation.features.registry import (
        get_implementation,
        is_default_implementation,
    )
    from audiagentic.foundation.features.state import get_implementation_state

    target_impl = active_implementation_id(project_root)
    if not target_impl:
        return {"implementation": None, "enabled": False, "is_default": False}

    desc = get_implementation(_COMPONENT_ID, target_impl)
    impl_state = get_implementation_state(project_root, _COMPONENT_ID, target_impl)
    return {
        "implementation": target_impl,
        "enabled": impl_state.enabled,
        "is_default": bool(desc and is_default_implementation(desc)),
    }


def gateway_list_implementations(project_root: Path) -> dict[str, Any]:
    from audiagentic.foundation.features.registry import (
        get_implementations,
        is_default_implementation,
    )

    active = active_implementation_id(project_root)
    impls = get_implementations(_COMPONENT_ID)
    return {
        "active": active,
        "implementations": {
            impl_id: {
                "display_name": desc.display_name,
                "description": desc.description,
                "is_default": is_default_implementation(desc),
            }
            for impl_id, desc in impls.items()
        },
    }


def gateway_select_implementation(project_root: Path, implementation_id: str) -> dict[str, Any]:
    from audiagentic.foundation.features.lifecycle import enable_implementation

    return enable_implementation(project_root, _COMPONENT_ID, implementation_id)


def gateway_get_config(project_root: Path, implementation_id: str | None = None) -> dict[str, Any]:
    """Return resolved config and settable-option schema for a gateway implementation.

    ``schema`` lets a caller discover every option an implementation accepts
    (type, description, required, default, allowed values) generically, then
    set any of them via ``gateway_set_config`` -- no implementation-specific
    tools (e.g. a hardcoded "set automatic startup timeout" tool) exist on
    this surface, per CREATING_A_COMPONENT.md's implementation-backed
    component rule.
    """
    from audiagentic.foundation.features.options import option_schema_to_dict
    from audiagentic.foundation.features.registry import (
        get_implementation,
        is_default_implementation,
    )
    from audiagentic.foundation.features.state import get_implementation_state

    target_impl = implementation_id or active_implementation_id(project_root)
    if not target_impl:
        return {"implementation": None, "config": {}, "schema": {}, "error": "No active implementation"}

    desc = get_implementation(_COMPONENT_ID, target_impl)
    impl_state = get_implementation_state(project_root, _COMPONENT_ID, target_impl)

    config = dict(impl_state.options) if impl_state.options else {}
    schema: dict[str, Any] = {}

    if desc and desc.options_schema:
        for key, opt_schema in desc.options_schema.items():
            if key not in config and opt_schema.default is not None:
                config[key] = opt_schema.default
            schema[key] = option_schema_to_dict(opt_schema)

    return {
        "implementation": target_impl,
        "config": config,
        "schema": schema,
        "enabled": impl_state.enabled,
        "is_default": bool(desc and is_default_implementation(desc)),
    }


def gateway_set_config(
    project_root: Path,
    implementation_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Validate and persist config updates for a gateway implementation."""
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.registry import get_implementation
    from audiagentic.foundation.features.state import (
        get_implementation_state,
        set_implementation_state,
    )

    desc = get_implementation(_COMPONENT_ID, implementation_id)
    if desc is None:
        raise AudiaGenticError(
            code="VAL-AGSV-027",
            kind="validation",
            message=f"unknown gateway implementation: {implementation_id!r}",
        )

    if desc.options_schema:
        for key, value in updates.items():
            option_schema = desc.options_schema.get(key)
            if option_schema is None:
                if not any(s.allow_unknown for s in desc.options_schema.values()):
                    raise AudiaGenticError(
                        code="VAL-AGSV-028",
                        kind="validation",
                        message=f"unknown option: {key!r} for gateway implementation {implementation_id!r}",
                        details={"valid_options": list(desc.options_schema.keys())},
                    )
            else:
                from audiagentic.foundation.features.options import validate_option
                try:
                    validate_option(key, value, option_schema)
                except (AudiaGenticError, ValueError) as exc:
                    raise AudiaGenticError(
                        code="VAL-AGSV-029",
                        kind="validation",
                        message=f"invalid value for option {key!r}: {exc}",
                    ) from exc

    impl_state = get_implementation_state(project_root, _COMPONENT_ID, implementation_id)
    options = dict(impl_state.options)
    options.update(updates)

    new_state = ImplementationState(enabled=impl_state.enabled, options=options)
    set_implementation_state(project_root, _COMPONENT_ID, implementation_id, new_state)

    return {
        "implementation": implementation_id,
        "config": options,
        "updated_keys": list(updates.keys()),
    }


def gateway_create_operation(
    project_root: Path,
    *,
    operation_id: str,
    kind: str,
    scope: dict[str, Any],
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Create a durable operator operation through the standalone authority."""
    from audiagentic.components.agents.gateway.service.bootstrap import start_or_attach_gateway

    client = start_or_attach_gateway()
    try:
        return client.create_gateway_operation(
            project_root,
            operation_id=operation_id,
            kind=kind,
            scope=scope,
            correlation_id=correlation_id,
        )
    finally:
        client.close()


def gateway_get_operation(project_root: Path, operation_id: str) -> dict[str, Any]:
    """Read the public projection of a durable gateway operation."""
    from audiagentic.components.agents.gateway.service.bootstrap import start_or_attach_gateway

    client = start_or_attach_gateway()
    try:
        return client.get_gateway_operation(project_root, operation_id)
    finally:
        client.close()


def gateway_get_retention_policy(project_root: Path) -> dict[str, Any]:
    """Return the redacted machine retention policy for operator inspection.

    The policy resolver is deliberately machine-scoped; this projection exposes
    only effect-relevant values and never the policy path or any project data.
    ``project_root`` is accepted for management-surface parity but is not used
    to resolve policy, preventing project configuration from weakening it.
    """
    del project_root
    from audiagentic.components.agents.gateway.operations.retention_policy import (
        load_retention_policy,
    )

    policy = load_retention_policy()
    return {
        "available": policy.available,
        "purge-enabled": policy.enabled,
        "minimum-archive-age-seconds": policy.minimum_archive_age_seconds,
        "max-batch-size": policy.max_batch_size,
        "policy-id": policy.policy_id,
        "policy-digest": policy.digest,
    }
