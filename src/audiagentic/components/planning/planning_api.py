"""Planning API facade — status/config plus re-exports of the item/review CRUD.

The MCP surfaces (planning_mcp, planning_manage_mcp) import from this module
only; item CRUD lives in items.py, review CRUD in reviews.py, and storage
helpers in item_store.py. All paths are resolved via planning_paths, which
reads from the active implementation descriptor's ``paths:`` block.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.planning.items import (
    create_item,
    delete_item,
    get_item,
    list_items,
    list_items_grouped,
    list_items_page,
    set_state,
    update_item,
)
from audiagentic.components.planning.reviews import (
    create_review,
    delete_review,
    get_review,
    list_reviews,
    list_reviews_page,
    set_review_state,
    update_review,
)
from audiagentic.foundation.components.hooks import ComponentStatusPayload
from audiagentic.foundation.contracts.errors import AudiaGenticError

__all__ = [
    "active_implementation_id",
    "planning_status",
    "planning_get_config",
    "planning_set_config",
    "list_standards",
    # items
    "create_item",
    "list_items",
    "list_items_grouped",
    "list_items_page",
    "get_item",
    "set_state",
    "update_item",
    "delete_item",
    # reviews
    "create_review",
    "list_reviews",
    "list_reviews_page",
    "get_review",
    "set_review_state",
    "update_review",
    "delete_review",
]

logger = logging.getLogger(__name__)

_COMPONENT_ID = "agent-planning"


def active_implementation_id(project_root: Path) -> str:
    """Return the enabled implementation ID, or the descriptor-defined default."""
    from audiagentic.foundation.features.registry import resolve_active_implementation

    return resolve_active_implementation(project_root, _COMPONENT_ID) or ""


def planning_status(project_root: Path) -> ComponentStatusPayload:
    """Return planning status: active implementation, item counts, config completeness.

    Configuration completeness is derived generically from the active
    implementation's options-schema via the shared features helper.

    ``enabled`` reflects whether the *planning component itself* is enabled
    (component-level, same meaning as elsewhere e.g. list_components rows).
    Whether the active implementation was explicitly selected (vs. picked as a
    fallback default) is reported under ``details.implementation``.
    """
    from audiagentic.foundation.features.config_status import implementation_status_payload

    return implementation_status_payload(
        project_root,
        _COMPONENT_ID,
        extra_details={
            "pending_items": len(list_items(project_root, state="active")),
            "completed_items": len(list_items(project_root, state="completed")),
        },
    )


def planning_get_config(project_root: Path, implementation_id: str | None = None) -> dict[str, Any]:
    """Return resolved config and settable-option schema for a planning implementation.

    ``schema`` lets a caller discover every option this implementation accepts
    (type, description, required, default, allowed values) generically, then
    set any of them via ``planning_set_config`` — no implementation-specific
    tools are needed on the planning MCP surface.
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


def planning_set_config(
    project_root: Path,
    implementation_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Validate and persist config updates for a planning implementation."""
    from audiagentic.foundation.features.base import ImplementationState
    from audiagentic.foundation.features.registry import get_implementation
    from audiagentic.foundation.features.state import (
        get_implementation_state,
        set_implementation_state,
    )

    desc = get_implementation(_COMPONENT_ID, implementation_id)
    if desc is None:
        raise AudiaGenticError(
            code="VAL-PLN-015",
            kind="validation",
            message="unknown planning implementation",
        )

    if desc.options_schema:
        for key, value in updates.items():
            schema = desc.options_schema.get(key)
            if schema is None:
                if not any(s.allow_unknown for s in desc.options_schema.values()):
                    raise AudiaGenticError(
                        code="VAL-PLN-016",
                        kind="validation",
                        message="unknown planning option",
                        details={"valid_options": list(desc.options_schema.keys())},
                    )
            else:
                from audiagentic.foundation.features.options import validate_option
                try:
                    validate_option(key, value, schema)
                except (AudiaGenticError, ValueError) as exc:
                    raise AudiaGenticError(
                        code="VAL-PLN-017",
                        kind="validation",
                        message="invalid value for planning option",
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


def list_standards(project_root: Path) -> list[dict[str, Any]]:
    """List architecture and design standards from implementation config.

    Reads the standards list from the active implementation descriptor's YAML.
    Returns a list of dicts with id, title, path, and description fields.
    """
    try:
        from audiagentic.foundation.features.registry import get_implementation
        impl_id = "planning-local-docs"
        desc = get_implementation("agent-planning", impl_id)
        if desc is not None:
            standards = desc.raw.get("standards", [])
            if standards:
                return standards
    except Exception:
        logger.debug("Could not load standards from implementation config", exc_info=True)
    return []
