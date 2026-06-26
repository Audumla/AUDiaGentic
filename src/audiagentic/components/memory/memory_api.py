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

from audiagentic.foundation.components.ids import COMPONENT_PROVIDERS
from audiagentic.foundation.components.registry import is_enabled as is_component_enabled
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.lifecycle import enable_implementation
from audiagentic.foundation.features.registry import get_implementation, get_implementations
from audiagentic.foundation.features.state import (
    get_component_state,
    get_implementation_state,
    set_implementation_state,
)

logger = logging.getLogger(__name__)

_COMPONENT_ID = "memory"

# Persisted config lives in the per-component feature state shard at:
#   .audiagentic/config/runtime/features/memory.yaml
# under implementations/<impl_id>/options.
# This path is managed by the features state API — no custom file paths needed.


def _active_implementation_id(project_root: Path) -> str:
    """Return the enabled implementation ID, or the first registered default."""
    component = get_component_state(project_root, _COMPONENT_ID)
    implementations = component.get("implementations") or {}
    if isinstance(implementations, dict):
        for impl_id, state in implementations.items():
            if isinstance(state, dict) and state.get("enabled"):
                return impl_id
    impls = get_implementations(_COMPONENT_ID)
    for impl_id in sorted(impls):
        if impls[impl_id].raw.get("default"):
            return impl_id
    return next(iter(sorted(impls)), "")


def memory_status(project_root: Path) -> dict[str, Any]:
    """Return memory component status: active implementation and configuration state.

    Reports only memory-owned facts. Provider support is not queried here —
    that's the providers component's responsibility.
    """
    active_impl = _active_implementation_id(project_root)
    if not active_impl:
        return {
            "active_implementation": None,
            "configured": False,
            "warning": "No memory implementation available",
        }

    impl_state = get_implementation_state(project_root, _COMPONENT_ID, active_impl)
    configured = bool(impl_state.enabled or impl_state.options)

    # Check last projected state
    component = get_component_state(project_root, _COMPONENT_ID)
    impl_data = (component.get("implementations") or {}).get(active_impl, {})
    last_projected = impl_data.get("last_projected")

    return {
        "active_implementation": active_impl,
        "configured": configured,
        "last_projected": last_projected,
    }


def memory_list_implementations(project_root: Path) -> dict[str, Any]:
    """List available memory implementations and the currently active one."""
    active_impl = _active_implementation_id(project_root)
    impls = get_implementations(_COMPONENT_ID)
    return {
        "active": active_impl,
        "implementations": {
            impl_id: {
                "display_name": desc.display_name,
                "description": desc.description,
                "is_default": bool(desc.raw.get("default")),
            }
            for impl_id, desc in impls.items()
        },
    }


def memory_select_implementation(project_root: Path, implementation_id: str) -> dict[str, Any]:
    """Switch the active memory implementation.

    With implementation-cardinality exclusive, enabling one disables all others.
    Triggers provider surface reconcile if the providers component is enabled.
    """
    result = enable_implementation(project_root, _COMPONENT_ID, implementation_id)

    if result.get("ok"):
        _trigger_surface_reconcile(project_root)

    return result


def memory_get_config(project_root: Path, implementation_id: str | None = None) -> dict[str, Any]:
    """Return resolved config for the active or requested implementation."""
    target_impl = implementation_id or _active_implementation_id(project_root)
    if not target_impl:
        return {"implementation": None, "config": {}, "error": "No active implementation"}

    desc = get_implementation(_COMPONENT_ID, target_impl)
    impl_state = get_implementation_state(project_root, _COMPONENT_ID, target_impl)

    config = dict(impl_state.options) if impl_state.options else {}

    # Apply defaults from descriptor options-schema
    if desc and desc.options_schema:
        for key, schema in desc.options_schema.items():
            if key not in config and schema.default is not None:
                config[key] = schema.default

    return {
        "implementation": target_impl,
        "config": config,
        "enabled": impl_state.enabled,
    }


def memory_set_config(
    project_root: Path,
    implementation_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Validate and persist config updates for an implementation.

    Triggers provider surface refresh on success.
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

    # Trigger provider surface reconcile
    _trigger_surface_reconcile(project_root)

    return {
        "implementation": implementation_id,
        "config": options,
        "updated_keys": list(updates.keys()),
    }


def _trigger_surface_reconcile(project_root: Path) -> None:
    """Trigger provider surface reconcile to project memory config into provider files."""
    if not is_component_enabled(COMPONENT_PROVIDERS, project_root):
        return
    try:
        from audiagentic.components.providers.surfaces.manager import (
            apply_provider_surfaces as apply_surfaces,
        )
        apply_surfaces(project_root)
    except Exception:
        logger.debug("Could not trigger surface reconcile after memory config change", exc_info=True)


def build_memory_contributions(project_root: Path | None = None) -> list[dict[str, Any]]:
    """Build dynamic surface contributions from active memory config.

    Returns a list of contribution dicts compatible with SurfaceContribution.
    Providers render these into their instruction/config files. Memory only
    exports provider-agnostic content: backend identity and status.
    """
    if project_root is None:
        return []

    active_impl = _active_implementation_id(project_root)
    if not active_impl:
        return []

    impl_state = get_implementation_state(project_root, _COMPONENT_ID, active_impl)
    config = dict(impl_state.options) if impl_state.options else {}

    if not config:
        return []

    desc = get_implementation(_COMPONENT_ID, active_impl)
    backend_name = desc.display_name if desc else active_impl

    base_url = config.get("base-url") or config.get("base_url", "")
    if not base_url:
        return []

    body_lines = [
        f"Memory is backed by {backend_name} at `{base_url}`.",
        "Use the hindsight MCP tools for long-term memory operations:",
        "- `hindsight_recall` — Search long-term memory",
        "- `hindsight_reflect` — Synthesize memories into answers",
        "- `hindsight_retain` — Store information in memory",
    ]

    return [
        {
            "contribution_id": f"memory/{active_impl}",
            "owner_component": _COMPONENT_ID,
            "title": "Memory (Hindsight)",
            "body": "\n".join(body_lines),
        }
    ]
