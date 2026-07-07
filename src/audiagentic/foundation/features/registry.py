from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory

from .base import (
    FEATURE_SCOPE_IMPLEMENTATION,
    BindingDescriptor,
    FeatureDescriptor,
    ImplementationDescriptor,
)

_features: dict[tuple[str, str, str], FeatureDescriptor] = {}
# Implementation-scoped features keyed by (parent, implementation, kind, feature_id)
# so the same (kind, feature_id) can be owned independently by different implementations.
_impl_features: dict[tuple[str, str, str, str], FeatureDescriptor] = {}
_implementations: dict[tuple[str, str], ImplementationDescriptor] = {}
_bindings: dict[tuple[str, str, str, str], BindingDescriptor] = {}
_binding_writers: dict[tuple[str, str, str], Callable[..., Any]] = {}

_registry_error: Any = make_error_factory("CON", "FREG", "feature-registry")
_logger = logging.getLogger(__name__)
_SELF_POPULATING = False


def _self_populate() -> None:
    global _SELF_POPULATING
    if _SELF_POPULATING or _features or _impl_features or _implementations or _bindings:
        return
    from audiagentic.foundation.components import registry as component_registry

    if getattr(component_registry, "_LOADING_DEFAULT_COMPONENTS", False):
        return
    from audiagentic.foundation.components.loader import register_all_components

    _SELF_POPULATING = True
    try:
        register_all_components()
    finally:
        _SELF_POPULATING = False


def clear() -> None:
    """Clear all feature registry state.

    Note: Feature registration is constrained to one component profile per process
    (CP05). This function is used by test fixtures and profile cache reset to
    allow re-registration under a different profile after explicit cache clearing.
    """
    _features.clear()
    _impl_features.clear()
    _implementations.clear()
    _bindings.clear()
    _binding_writers.clear()


def register(descriptor: FeatureDescriptor | ImplementationDescriptor | BindingDescriptor) -> None:
    if isinstance(descriptor, ImplementationDescriptor):
        _implementations[descriptor.key] = descriptor
        return
    if isinstance(descriptor, BindingDescriptor):
        _bindings[descriptor.key] = descriptor
        return
    if descriptor.scope == FEATURE_SCOPE_IMPLEMENTATION:
        if not descriptor.implementation:
            raise _registry_error(
                1,
                f"implementation-scoped feature {descriptor.key} must name an implementation",
                key=descriptor.key,
            )
        _impl_features[
            (descriptor.parent, descriptor.implementation, descriptor.kind, descriptor.feature_id)
        ] = descriptor
        return
    _features[descriptor.key] = descriptor


def get_feature(parent: str, kind: str, feature_id: str) -> FeatureDescriptor | None:
    _self_populate()
    return _features.get((parent, kind, feature_id))


def get_features(parent: str, kind: str | None = None) -> dict[str, FeatureDescriptor]:
    _self_populate()
    result: dict[str, FeatureDescriptor] = {}
    for (p, k, feature_id), descriptor in _features.items():
        if p != parent:
            continue
        if kind is not None and k != kind:
            continue
        result[feature_id] = descriptor
    return result


def all_features() -> dict[tuple[str, str, str], FeatureDescriptor]:
    _self_populate()
    return dict(_features)


def get_implementation_feature(
    parent: str, implementation: str, kind: str, feature_id: str
) -> FeatureDescriptor | None:
    _self_populate()
    return _impl_features.get((parent, implementation, kind, feature_id))


def get_implementation_features(
    parent: str, implementation: str, kind: str | None = None
) -> dict[str, FeatureDescriptor]:
    """Return implementation-scoped features owned by one implementation (no cross-product)."""
    _self_populate()
    result: dict[str, FeatureDescriptor] = {}
    for (p, impl, k, feature_id), descriptor in _impl_features.items():
        if p != parent or impl != implementation:
            continue
        if kind is not None and k != kind:
            continue
        result[feature_id] = descriptor
    return result


def get_implementation(parent: str, implementation_id: str) -> ImplementationDescriptor | None:
    _self_populate()
    return _implementations.get((parent, implementation_id))


def get_implementations(parent: str) -> dict[str, ImplementationDescriptor]:
    _self_populate()
    return {
        implementation_id: descriptor
        for (p, implementation_id), descriptor in _implementations.items()
        if p == parent
    }


def all_implementations() -> dict[tuple[str, str], ImplementationDescriptor]:
    _self_populate()
    return dict(_implementations)


def resolve_active_implementation(
    project_root,
    component_id: str,
    *,
    fallback: str | None = None,
) -> str | None:
    """Return the active implementation ID for a component.

    Precedence: (1) first implementation marked enabled in persisted component
    state; (2) implementation whose descriptor declares ``default: true``;
    (3) first sorted implementation ID; (4) ``fallback``. State/registry access
    failures resolve to ``fallback`` rather than raising — resolution must work
    during early bootstrap and in tests with partially populated state.
    """
    try:
        from .state import get_component_state

        component = get_component_state(project_root, component_id)
        implementations = component.get("implementations") or {}
        if isinstance(implementations, dict):
            for impl_id, state in implementations.items():
                if isinstance(state, dict) and state.get("enabled"):
                    return impl_id
        impls = get_implementations(component_id)
        for impl_id in sorted(impls):
            if impls[impl_id].raw.get("default"):
                return impl_id
        return next(iter(sorted(impls)), fallback)
    except Exception:
        _logger.debug(
            "Could not resolve active implementation for %s", component_id, exc_info=True
        )
        return fallback


def is_default_implementation(descriptor: ImplementationDescriptor) -> bool:
    """True if this implementation is the schema-declared default (``default: true``).

    Distinct from "actively selected": an implementation can be the active one
    (returned by whatever resolves the active implementation) purely because it's
    the default and nothing else was ever explicitly enabled in persisted state.
    """
    return bool(descriptor.raw.get("default"))


def get_binding(parent: str, implementation: str, feature_kind: str, feature: str) -> BindingDescriptor | None:
    _self_populate()
    return _bindings.get((parent, implementation, feature_kind, feature))


def get_bindings(parent: str) -> dict[tuple[str, str, str], BindingDescriptor]:
    _self_populate()
    return {
        (implementation, feature_kind, feature): descriptor
        for (p, implementation, feature_kind, feature), descriptor in _bindings.items()
        if p == parent
    }


def all_bindings() -> dict[tuple[str, str, str, str], BindingDescriptor]:
    _self_populate()
    return dict(_bindings)


def register_binding_writer(
    parent: str,
    writer_key: str,
    writer: Callable[..., Any],
    *,
    projection_kind: str = "default",
) -> None:
    _binding_writers[(parent, projection_kind, writer_key)] = writer


def get_binding_writer(
    parent: str,
    writer_key: str,
    *,
    projection_kind: str = "default",
) -> Callable[..., Any] | None:
    return _binding_writers.get((parent, projection_kind, writer_key))


def all_binding_writers() -> dict[tuple[str, str, str], Callable[..., Any]]:
    return dict(_binding_writers)
