from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

from .options import validate_option
from .registry import (
    get_feature,
    get_implementation,
    get_implementation_feature,
    get_implementations,
)
from .state import (
    get_feature_state,
    get_implementation_feature_state,
    get_implementation_state,
    set_feature_state,
    set_implementation_feature_state,
    set_implementation_state,
)


def _implementation_cardinality(parent: str) -> str | None:
    from audiagentic.foundation.components.registry import get_descriptor

    descriptor = get_descriptor(parent)
    return descriptor.implementation_cardinality if descriptor else None


def enable_feature(project_root: Path, parent: str, kind: str, feature_id: str) -> dict[str, Any]:
    descriptor = get_feature(parent, kind, feature_id)
    if descriptor is None:
        return {"ok": False, "error": f"unknown feature: {parent}.{kind}.{feature_id}"}
    state = get_feature_state(project_root, parent, kind, feature_id)
    set_feature_state(project_root, parent, kind, feature_id, type(state)(enabled=True, options=state.options))
    return {"ok": True, "parent": parent, "kind": kind, "feature": feature_id, "enabled": True}


def disable_feature(project_root: Path, parent: str, kind: str, feature_id: str) -> dict[str, Any]:
    descriptor = get_feature(parent, kind, feature_id)
    if descriptor is None:
        return {"ok": False, "error": f"unknown feature: {parent}.{kind}.{feature_id}"}
    state = get_feature_state(project_root, parent, kind, feature_id)
    set_feature_state(project_root, parent, kind, feature_id, type(state)(enabled=False, options=state.options))
    return {"ok": True, "parent": parent, "kind": kind, "feature": feature_id, "enabled": False}


def set_feature_option(
    project_root: Path,
    parent: str,
    kind: str,
    feature_id: str,
    key: str,
    value: Any,
) -> dict[str, Any]:
    descriptor = get_feature(parent, kind, feature_id)
    if descriptor is None:
        return {"ok": False, "error": f"unknown feature: {parent}.{kind}.{feature_id}"}
    schema = descriptor.options_schema.get(key)
    if schema is None:
        return {"ok": False, "error": f"unknown option: {key}"}
    try:
        validate_option(key, value, schema)
    except (AudiaGenticError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    state = get_feature_state(project_root, parent, kind, feature_id)
    options = dict(state.options)
    options[key] = value
    set_feature_state(project_root, parent, kind, feature_id, type(state)(enabled=state.enabled, options=options))
    return {"ok": True, "parent": parent, "kind": kind, "feature": feature_id, "option": key, "value": value}


def reset_feature_option(
    project_root: Path,
    parent: str,
    kind: str,
    feature_id: str,
    key: str,
) -> dict[str, Any]:
    descriptor = get_feature(parent, kind, feature_id)
    if descriptor is None:
        return {"ok": False, "error": f"unknown feature: {parent}.{kind}.{feature_id}"}
    state = get_feature_state(project_root, parent, kind, feature_id)
    options = dict(state.options)
    removed = key in options
    options.pop(key, None)
    set_feature_state(project_root, parent, kind, feature_id, type(state)(enabled=state.enabled, options=options))
    return {"ok": True, "parent": parent, "kind": kind, "feature": feature_id, "option": key, "removed": removed}


def enable_implementation(project_root: Path, parent: str, implementation_id: str) -> dict[str, Any]:
    descriptor = get_implementation(parent, implementation_id)
    if descriptor is None:
        return {"ok": False, "error": f"unknown implementation: {parent}.{implementation_id}"}
    cardinality = _implementation_cardinality(parent)
    if cardinality == "exclusive":
        for other_id in get_implementations(parent):
            if other_id == implementation_id:
                continue
            other_state = get_implementation_state(project_root, parent, other_id)
            if other_state.enabled:
                set_implementation_state(
                    project_root,
                    parent,
                    other_id,
                    type(other_state)(enabled=False, options=other_state.options),
                )
    state = get_implementation_state(project_root, parent, implementation_id)
    set_implementation_state(
        project_root,
        parent,
        implementation_id,
        type(state)(enabled=True, options=state.options),
    )
    return {
        "ok": True,
        "parent": parent,
        "implementation": implementation_id,
        "enabled": True,
        "cardinality": cardinality,
    }


def disable_implementation(project_root: Path, parent: str, implementation_id: str) -> dict[str, Any]:
    descriptor = get_implementation(parent, implementation_id)
    if descriptor is None:
        return {"ok": False, "error": f"unknown implementation: {parent}.{implementation_id}"}
    state = get_implementation_state(project_root, parent, implementation_id)
    set_implementation_state(
        project_root,
        parent,
        implementation_id,
        type(state)(enabled=False, options=state.options),
    )
    return {"ok": True, "parent": parent, "implementation": implementation_id, "enabled": False}


def _impl_feature_result(
    parent: str, implementation: str, kind: str, feature_id: str, **extra: Any
) -> dict[str, Any]:
    return {
        "ok": True,
        "parent": parent,
        "implementation": implementation,
        "kind": kind,
        "feature": feature_id,
        **extra,
    }


def enable_implementation_feature(
    project_root: Path, parent: str, implementation: str, kind: str, feature_id: str
) -> dict[str, Any]:
    if get_implementation_feature(parent, implementation, kind, feature_id) is None:
        return {"ok": False, "error": f"unknown implementation feature: {parent}.{implementation}.{kind}.{feature_id}"}
    state = get_implementation_feature_state(project_root, parent, implementation, kind, feature_id)
    set_implementation_feature_state(
        project_root, parent, implementation, kind, feature_id, type(state)(enabled=True, options=state.options)
    )
    return _impl_feature_result(parent, implementation, kind, feature_id, enabled=True)


def disable_implementation_feature(
    project_root: Path, parent: str, implementation: str, kind: str, feature_id: str
) -> dict[str, Any]:
    if get_implementation_feature(parent, implementation, kind, feature_id) is None:
        return {"ok": False, "error": f"unknown implementation feature: {parent}.{implementation}.{kind}.{feature_id}"}
    state = get_implementation_feature_state(project_root, parent, implementation, kind, feature_id)
    set_implementation_feature_state(
        project_root, parent, implementation, kind, feature_id, type(state)(enabled=False, options=state.options)
    )
    return _impl_feature_result(parent, implementation, kind, feature_id, enabled=False)


def set_implementation_feature_option(
    project_root: Path,
    parent: str,
    implementation: str,
    kind: str,
    feature_id: str,
    key: str,
    value: Any,
) -> dict[str, Any]:
    descriptor = get_implementation_feature(parent, implementation, kind, feature_id)
    if descriptor is None:
        return {"ok": False, "error": f"unknown implementation feature: {parent}.{implementation}.{kind}.{feature_id}"}
    schema = descriptor.options_schema.get(key)
    if schema is None:
        return {"ok": False, "error": f"unknown option: {key}"}
    try:
        validate_option(key, value, schema)
    except (AudiaGenticError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}
    state = get_implementation_feature_state(project_root, parent, implementation, kind, feature_id)
    options = dict(state.options)
    options[key] = value
    set_implementation_feature_state(
        project_root, parent, implementation, kind, feature_id, type(state)(enabled=state.enabled, options=options)
    )
    return _impl_feature_result(parent, implementation, kind, feature_id, option=key, value=value)
