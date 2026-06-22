from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file

from .base import (
    FEATURE_SCOPE_IMPLEMENTATION,
    FEATURE_SCOPE_SHARED,
    BindingDescriptor,
    DescriptorType,
    FeatureDescriptor,
    ImplementationDescriptor,
)
from .options import load_option_schema
from .registry import register


def _descriptor_error(path: Path, code: str, message: str, **details: Any) -> AudiaGenticError:
    return AudiaGenticError(
        code=code,
        kind="feature-descriptors",
        message=message,
        details={"path": str(path), **details},
    )


def _require_string(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise _descriptor_error(
            path,
            "VAL-FDESC-001",
            "feature descriptor field must be a non-empty string",
            field=key,
            value=value,
        )
    return value


def load_feature_from_yaml(path: Path) -> FeatureDescriptor:
    data = load_yaml_file(path)
    if data.get("type") != "feature":
        raise _descriptor_error(
            path,
            "VAL-FDESC-002",
            "expected feature descriptor type",
            expected="feature",
            actual=data.get("type"),
        )
    parent = _require_string(data, "parent", path)
    kind = _require_string(data, "kind", path)
    feature_id = _require_string(data, "id", path)
    implementation = data.get("implementation")
    if implementation is not None and not isinstance(implementation, str):
        raise _descriptor_error(
            path,
            "VAL-FDESC-003",
            "feature implementation field must be a string",
            field="implementation",
            value=implementation,
        )
    scope = data.get("scope") or (FEATURE_SCOPE_IMPLEMENTATION if implementation else FEATURE_SCOPE_SHARED)
    if scope not in {FEATURE_SCOPE_SHARED, FEATURE_SCOPE_IMPLEMENTATION}:
        raise _descriptor_error(
            path,
            "VAL-FDESC-004",
            "invalid feature scope",
            field="scope",
            value=scope,
            allowed=[FEATURE_SCOPE_SHARED, FEATURE_SCOPE_IMPLEMENTATION],
        )
    dependencies = data.get("dependencies") or {}
    if not isinstance(dependencies, dict):
        raise _descriptor_error(
            path,
            "VAL-FDESC-005",
            "feature dependencies must be a mapping",
            field="dependencies",
            value=dependencies,
        )
    descriptor = FeatureDescriptor(
        parent=parent,
        kind=kind,
        feature_id=feature_id,
        display_name=data.get("display-name", feature_id),
        description=data.get("description", ""),
        scope=scope,
        implementation=implementation,
        dependencies=dict(dependencies),
        options_schema=load_option_schema(data.get("options-schema")),
        raw=data,
    )
    register(descriptor)
    return descriptor


def load_implementation_from_yaml(path: Path) -> ImplementationDescriptor:
    data = load_yaml_file(path)
    if data.get("type") != "implementation":
        raise _descriptor_error(
            path,
            "VAL-FDESC-006",
            "expected implementation descriptor type",
            expected="implementation",
            actual=data.get("type"),
        )
    parent = _require_string(data, "parent", path)
    implementation_id = _require_string(data, "id", path)
    dependencies = data.get("dependencies") or {}
    if not isinstance(dependencies, dict):
        raise _descriptor_error(
            path,
            "VAL-FDESC-007",
            "implementation dependencies must be a mapping",
            field="dependencies",
            value=dependencies,
        )
    descriptor = ImplementationDescriptor(
        parent=parent,
        implementation_id=implementation_id,
        display_name=data.get("display-name", implementation_id),
        description=data.get("description", ""),
        dependencies=dict(dependencies),
        options_schema=load_option_schema(data.get("options-schema")),
        raw=data,
    )
    register(descriptor)
    return descriptor


def load_binding_from_yaml(path: Path) -> BindingDescriptor:
    data = load_yaml_file(path)
    if data.get("type") != "binding":
        raise _descriptor_error(
            path,
            "VAL-FDESC-008",
            "expected binding descriptor type",
            expected="binding",
            actual=data.get("type"),
        )
    parent = _require_string(data, "parent", path)
    implementation = _require_string(data, "implementation", path)
    feature = _require_string(data, "feature", path)
    feature_kind = _require_string(data, "feature-kind", path)
    uses_dependencies = data.get("uses-dependencies") or []
    if not isinstance(uses_dependencies, list) or not all(isinstance(item, str) for item in uses_dependencies):
        raise _descriptor_error(
            path,
            "VAL-FDESC-009",
            "binding uses-dependencies must be a list of strings",
            field="uses-dependencies",
            value=uses_dependencies,
        )
    projection = data.get("projection") or {}
    if projection and not isinstance(projection, dict):
        raise _descriptor_error(
            path,
            "VAL-FDESC-010",
            "binding projection must be a mapping",
            field="projection",
            value=projection,
        )
    writer_key = projection.get("writer-key", "")
    if writer_key is not None and not isinstance(writer_key, str):
        raise _descriptor_error(
            path,
            "VAL-FDESC-011",
            "binding projection.writer-key must be a string",
            field="projection.writer-key",
            value=writer_key,
        )
    descriptor = BindingDescriptor(
        parent=parent,
        implementation=implementation,
        feature=feature,
        feature_kind=feature_kind,
        uses_dependencies=tuple(uses_dependencies),
        projection_writer_key=writer_key or "",
        options_schema=load_option_schema(data.get("options-schema")),
        raw=data,
    )
    register(descriptor)
    return descriptor


def register_from_yaml(path: Path) -> FeatureDescriptor | ImplementationDescriptor | BindingDescriptor:
    data = load_yaml_file(path)
    type_value = data.get("type")
    if not isinstance(type_value, str) or not type_value:
        raise _descriptor_error(
            path,
            "VAL-FDESC-012",
            "descriptor type field must be a non-empty string",
            field="type",
            value=type_value,
        )
    try:
        descriptor_type = DescriptorType.from_string(type_value)
    except ValueError:
        raise _descriptor_error(
            path,
            "VAL-FDESC-012",
            "unsupported feature descriptor type",
            field="type",
            value=type_value,
            supported=[t.value for t in DescriptorType],
        )
    if descriptor_type == DescriptorType.FEATURE:
        return load_feature_from_yaml(path)
    if descriptor_type == DescriptorType.IMPLEMENTATION:
        return load_implementation_from_yaml(path)
    if descriptor_type == DescriptorType.BINDING:
        return load_binding_from_yaml(path)
    # Unreachable, but keep for type safety
    raise _descriptor_error(
        path,
        "VAL-FDESC-012",
        "unsupported feature descriptor type",
        field="type",
        value=type_value,
        supported=[t.value for t in DescriptorType],
    )


def load_features_from_dir(
    config_dir: Path,
    *,
    recursive: bool = False,
) -> list[FeatureDescriptor | ImplementationDescriptor | BindingDescriptor]:
    pattern = "**/*.yaml" if recursive else "*.yaml"
    descriptors: list[FeatureDescriptor | ImplementationDescriptor | BindingDescriptor] = []
    valid_types = {t.value for t in DescriptorType}
    for path in sorted(config_dir.glob(pattern)):
        data = load_yaml_file(path)
        if data.get("type") in valid_types:
            descriptors.append(register_from_yaml(path))
    return descriptors
