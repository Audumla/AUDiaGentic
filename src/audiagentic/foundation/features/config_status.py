"""Generic configuration-completeness evaluation for schema-backed features.

A configurable unit (implementation or feature) is *configured* when every
option its schema marks ``required`` has a value — either supplied by the user
or provided as a schema default. This module derives that state generically
from an ``OptionSchema`` map plus an options mapping; it holds no knowledge of
any specific component, implementation, or option name.

Components surface the result through their own status APIs. The derivation
lives here so every schema-backed component reports "configured" and "what's
missing" identically instead of re-inventing the rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .base import OptionSchema


@dataclass(frozen=True)
class MissingOption:
    """A required option that has no value in the resolved configuration."""
    key: str
    description: str = ""


@dataclass(frozen=True)
class ConfigStatus:
    """Configuration completeness for one schema-backed unit."""
    configured: bool
    missing_required: tuple[MissingOption, ...] = ()
    effective_options: dict[str, Any] = field(default_factory=dict)


def evaluate_config(
    schema: dict[str, OptionSchema],
    options: dict[str, Any],
) -> ConfigStatus:
    """Evaluate configuration completeness for a schema + supplied options.

    An option satisfies its ``required`` constraint when it is present in the
    supplied options or the schema provides a non-``None`` default. Pure and
    side-effect free — never raises on unknown/invalid values, since this is a
    read-only status derivation, not validation.
    """
    effective: dict[str, Any] = {
        key: opt.default for key, opt in schema.items() if opt.default is not None
    }
    effective.update(options)

    missing = tuple(
        MissingOption(key=key, description=opt.description)
        for key, opt in schema.items()
        if opt.required and key not in effective
    )
    return ConfigStatus(
        configured=not missing,
        missing_required=missing,
        effective_options=effective,
    )


@dataclass(frozen=True)
class ImplementationConfigStatus:
    """Config completeness plus enablement for one implementation.

    Bundles the enablement flag (did the user turn it on) with configuration
    completeness (does it have everything it needs) — orthogonal concerns a
    component's status view typically reports together.
    """
    implementation_id: str
    enabled: bool
    configured: bool
    missing_required: tuple[MissingOption, ...] = ()
    effective_options: dict[str, Any] = field(default_factory=dict)


def implementation_status_payload(
    project_root: Path,
    component_id: str,
    *,
    extra_details: dict[str, Any] | None = None,
):
    """Build the standard ComponentStatusPayload for an implementation-backed component.

    Encapsulates the shared status-hook pattern: component enablement, active
    implementation resolution, config completeness, the ``missing_required``
    mapping, and ``details.implementation`` = {enabled, is_default}.
    ``extra_details`` is merged into ``details`` for component-specific facts.
    When the component has no resolvable implementation the payload reports
    configured=False with ``active_implementation=None``.
    """
    from audiagentic.foundation.components import is_enabled
    from audiagentic.foundation.components.hooks import ComponentStatusPayload

    from .registry import (
        get_implementation,
        is_default_implementation,
        resolve_active_implementation,
    )

    component_enabled = is_enabled(component_id, project_root)
    details: dict[str, Any] = dict(extra_details or {})
    active = resolve_active_implementation(project_root, component_id) or ""
    if not active:
        return ComponentStatusPayload(
            enabled=component_enabled,
            configured=False,
            active_implementation=None,
            missing_required=[],
            details=details,
        )

    status = implementation_config_status(project_root, component_id, active)
    desc = get_implementation(component_id, active)
    details["implementation"] = {
        "enabled": status.enabled,
        "is_default": bool(desc and is_default_implementation(desc)),
    }
    return ComponentStatusPayload(
        enabled=component_enabled,
        configured=status.configured,
        active_implementation=active,
        missing_required=[
            {"option": m.key, "description": m.description}
            for m in status.missing_required
        ],
        details=details,
    )


def implementation_config_status(
    project_root: Path,
    parent: str,
    implementation_id: str,
) -> ImplementationConfigStatus:
    """Resolve config completeness for a registered implementation from state.

    Generic across every implementation-backed component: it reads the
    implementation's declared ``options_schema`` and its persisted
    ``ImplementationState``, then applies :func:`evaluate_config`.
    """
    from .registry import get_implementation
    from .state import get_implementation_state

    descriptor = get_implementation(parent, implementation_id)
    schema = descriptor.options_schema if descriptor else {}
    state = get_implementation_state(project_root, parent, implementation_id)
    status = evaluate_config(schema, state.options)
    return ImplementationConfigStatus(
        implementation_id=implementation_id,
        enabled=state.enabled,
        configured=status.configured,
        missing_required=status.missing_required,
        effective_options=status.effective_options,
    )
