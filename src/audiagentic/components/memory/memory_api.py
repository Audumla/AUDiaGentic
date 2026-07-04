"""Memory component API — implementation selection, config, and status.

Routes business logic for the ag-memory-mgmt MCP server. Follows the thin-MCP
pattern: MCP layer delegates to this module, which uses the features lifecycle
and state APIs for persistence.

Ownership boundary: memory owns backend state only. Provider adaptation lives
in the providers component — memory does not enumerate provider IDs, write
provider file paths, or branch on provider-specific syntax.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.components.hooks import ComponentStatusPayload
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.lifecycle import enable_implementation
from audiagentic.foundation.features.registry import (
    get_implementation,
    get_implementations,
    resolve_active_implementation,
)
from audiagentic.foundation.features.state import (
    get_implementation_state,
    set_implementation_state,
)

logger = logging.getLogger(__name__)

_COMPONENT_ID = "memory"

# Persisted config lives in the per-component feature state shard at:
#   .audiagentic/config/runtime/features/memory.yaml
# under implementations/<impl_id>/options.
# This path is managed by the features state API — no custom file paths needed.


def memory_status(project_root: Path) -> ComponentStatusPayload:
    """Return memory component status: active implementation and configuration state.

    Reports only memory-owned facts. Provider support is not queried here —
    that's the providers component's responsibility.

    ``enabled`` reflects whether the *memory component itself* is enabled
    (matches the component-level ``enabled`` used elsewhere, e.g. list_components
    rows). Whether the active implementation was explicitly selected (vs. picked
    as a fallback default) is a separate, implementation-scoped fact and is
    reported under ``details.implementation`` instead — reusing the top-level
    ``enabled`` key for that would collide with its component-level meaning in
    every other status-hook payload.
    """
    from audiagentic.foundation.features.config_status import implementation_status_payload

    payload = implementation_status_payload(project_root, _COMPONENT_ID)
    if payload.active_implementation is None:
        return ComponentStatusPayload(
            enabled=payload.enabled,
            configured=False,
            active_implementation=None,
            missing_required=[],
            details={"warning": "No memory implementation available"},
        )
    return payload


def memory_list_implementations(project_root: Path) -> dict[str, Any]:
    """List available memory implementations and the currently active one."""
    from audiagentic.foundation.features.registry import is_default_implementation

    active_impl = resolve_active_implementation(project_root, _COMPONENT_ID) or ""
    impls = get_implementations(_COMPONENT_ID)
    return {
        "active": active_impl,
        "implementations": {
            impl_id: {
                "display_name": desc.display_name,
                "description": desc.description,
                "is_default": is_default_implementation(desc),
            }
            for impl_id, desc in impls.items()
        },
    }


def memory_select_implementation(project_root: Path, implementation_id: str) -> dict[str, Any]:
    """Switch the active memory implementation.

    With implementation-cardinality exclusive, enabling one disables all others.
    Publishes a lifecycle event so the observer can trigger Hindsight reconciliation.
    Memory core does not call provider code directly.
    """
    result = enable_implementation(project_root, _COMPONENT_ID, implementation_id)

    if result.get("ok"):
        result["needs_provider_recipe_refresh"] = True
        from audiagentic.foundation.event import COMPONENT_CONFIG_CHANGED, DeliveryMode, get_bus

        get_bus().publish(
            COMPONENT_CONFIG_CHANGED,
            {"component_id": _COMPONENT_ID, "project_root": project_root},
            mode=DeliveryMode.ASYNC,
        )

    return result


def memory_hindsight_status(project_root: Path) -> dict[str, Any]:
    """Return per-provider Hindsight integration status for all enabled providers.

    Delegates to contained Hindsight recipe system; memory core does not import
    provider services directly. Returns empty payload when Hindsight is not
    configured or no backend is available.
    """
    from audiagentic.components.memory.hindsight.provision import build_hindsight_status_report

    return build_hindsight_status_report(project_root)


def memory_get_config(project_root: Path, implementation_id: str | None = None) -> dict[str, Any]:
    """Return resolved config and settable-option schema for an implementation.

    ``schema`` lets a caller discover every option this implementation accepts
    (type, description, required, default, allowed values) generically, then
    set any of them via ``memory_set_config`` — no implementation-specific
    tools are needed on the memory MCP surface.
    """
    from audiagentic.foundation.features.options import option_schema_to_dict
    from audiagentic.foundation.features.registry import is_default_implementation

    target_impl = implementation_id or resolve_active_implementation(project_root, _COMPONENT_ID) or ""
    if not target_impl:
        return {"implementation": None, "config": {}, "schema": {}, "error": "No active implementation"}

    desc = get_implementation(_COMPONENT_ID, target_impl)
    impl_state = get_implementation_state(project_root, _COMPONENT_ID, target_impl)

    config = dict(impl_state.options) if impl_state.options else {}
    schema: dict[str, Any] = {}

    # Apply defaults from descriptor options-schema
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


def memory_set_config(
    project_root: Path,
    implementation_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Validate and persist config updates for an implementation.

    Returns a provider recipe refresh hint on success. Providers decide whether
    and how to reconcile their own integrations.

    Publishes ``lifecycle.component.config_changed`` so the memory observer can
    trigger Hindsight reconciliation — correctness is guaranteed by the observer,
    not by callers invoking reconciliation synchronously.
    """
    desc = get_implementation(_COMPONENT_ID, implementation_id)
    if desc is None:
        raise AudiaGenticError(
            code="VAL-MEM-001",
            kind="validation",
            message=f"unknown memory implementation: {implementation_id!r}",
        )

    # Validate options against schema
    if desc.options_schema:
        for key, value in updates.items():
            schema = desc.options_schema.get(key)
            if schema is None:
                if not any(s.allow_unknown for s in desc.options_schema.values()):
                    raise AudiaGenticError(
                        code="VAL-MEM-002",
                        kind="validation",
                        message=f"unknown option: {key!r} for implementation {implementation_id!r}",
                        details={"valid_options": list(desc.options_schema.keys())},
                    )
            else:
                from audiagentic.foundation.features.options import validate_option
                try:
                    validate_option(key, value, schema)
                except (AudiaGenticError, ValueError) as exc:
                    raise AudiaGenticError(
                        code="VAL-MEM-003",
                        kind="validation",
                        message=f"invalid value for option {key!r}: {exc}",
                    ) from exc

    # Merge with existing state
    impl_state = get_implementation_state(project_root, _COMPONENT_ID, implementation_id)
    options = dict(impl_state.options)
    options.update(updates)

    # Persist
    new_state = ImplementationState(enabled=impl_state.enabled, options=options)
    set_implementation_state(project_root, _COMPONENT_ID, implementation_id, new_state)

    from audiagentic.foundation.event import COMPONENT_CONFIG_CHANGED, DeliveryMode, get_bus

    get_bus().publish(
        COMPONENT_CONFIG_CHANGED,
        {"component_id": _COMPONENT_ID, "project_root": project_root},
        mode=DeliveryMode.ASYNC,
    )

    return {
        "implementation": implementation_id,
        "config": options,
        "updated_keys": list(updates.keys()),
        "needs_provider_recipe_refresh": True,
    }
