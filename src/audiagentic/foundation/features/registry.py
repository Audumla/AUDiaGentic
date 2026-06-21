from __future__ import annotations

from collections.abc import Callable
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError, make_error

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


def _registry_error(code_number: int, message: str, **details: Any) -> AudiaGenticError:
    return make_error(
        prefix="CON",
        component="FREG",
        number=code_number,
        kind="feature-registry",
        message=message,
        details=details,
    )


def clear() -> None:
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
    return _features.get((parent, kind, feature_id))


def get_features(parent: str, kind: str | None = None) -> dict[str, FeatureDescriptor]:
    result: dict[str, FeatureDescriptor] = {}
    for (p, k, feature_id), descriptor in _features.items():
        if p != parent:
            continue
        if kind is not None and k != kind:
            continue
        result[feature_id] = descriptor
    return result


def all_features() -> dict[tuple[str, str, str], FeatureDescriptor]:
    return dict(_features)


def get_implementation_feature(
    parent: str, implementation: str, kind: str, feature_id: str
) -> FeatureDescriptor | None:
    return _impl_features.get((parent, implementation, kind, feature_id))


def get_implementation_features(
    parent: str, implementation: str, kind: str | None = None
) -> dict[str, FeatureDescriptor]:
    """Return implementation-scoped features owned by one implementation (no cross-product)."""
    result: dict[str, FeatureDescriptor] = {}
    for (p, impl, k, feature_id), descriptor in _impl_features.items():
        if p != parent or impl != implementation:
            continue
        if kind is not None and k != kind:
            continue
        result[feature_id] = descriptor
    return result


def get_implementation(parent: str, implementation_id: str) -> ImplementationDescriptor | None:
    return _implementations.get((parent, implementation_id))


def get_implementations(parent: str) -> dict[str, ImplementationDescriptor]:
    return {
        implementation_id: descriptor
        for (p, implementation_id), descriptor in _implementations.items()
        if p == parent
    }


def all_implementations() -> dict[tuple[str, str], ImplementationDescriptor]:
    return dict(_implementations)


def get_binding(parent: str, implementation: str, feature_kind: str, feature: str) -> BindingDescriptor | None:
    return _bindings.get((parent, implementation, feature_kind, feature))


def get_bindings(parent: str) -> dict[tuple[str, str, str], BindingDescriptor]:
    return {
        (implementation, feature_kind, feature): descriptor
        for (p, implementation, feature_kind, feature), descriptor in _bindings.items()
        if p == parent
    }


def all_bindings() -> dict[tuple[str, str, str, str], BindingDescriptor]:
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
