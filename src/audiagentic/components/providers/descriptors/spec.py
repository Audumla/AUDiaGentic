"""Declarative descriptor loader with YAML file support.

Provides the mechanism behind PROVIDER_SPEC:
    load YAML → resolve dotpath hooks → build step tree → construct typed descriptor

The ``DescriptorSpec`` class declares how each YAML key maps to a Python field.
Field handling kinds:
    - data: literal value (str, bool, int, list)
    - ref: module:dotpath string, resolved at load time
    - step: workflow step spec dict, built via workflow.invocation.from_spec
    - nested: sub-dict mapped by a builder function

Lives with its only consumer (the provider descriptor loader); promote back to
foundation only if a second descriptor type actually adopts it.

Error codes:
    VAL-DESC-001 — declarative configuration reference resolution failure
    VAL-DESC-002 — step build failure (from workflow.invocation.from_spec)
    VAL-DESC-003 — required field missing from YAML
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.config.refs import resolve_ref
from audiagentic.foundation.contracts.errors import AudiaGenticError


@dataclass(frozen=True)
class FieldSpec:
    """Declares how a YAML key maps to a Python field.

    Attributes:
        yaml_key: Key name in the YAML file.
        kind: Handling kind — data, ref, step, nested.
        required: Whether the field must be present.
        default: Default value if absent and not required.
        builder: For nested kind, function that builds the object from a dict.
        converter: For data kind, function that transforms the raw value.
    """
    yaml_key: str
    kind: str  # "data" | "ref" | "step" | "nested"
    required: bool = False
    default: Any = None
    builder: Callable[[dict[str, Any]], Any] | None = None
    converter: Callable[[Any], Any] | None = None


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file and return its contents as a dict."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AudiaGenticError(
            code="IO-DESC-001",
            kind="descriptor",
            message=f"Cannot read descriptor file {path}: {exc}",
        ) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise AudiaGenticError(
            code="VAL-DESC-003",
            kind="descriptor",
            message=f"Invalid YAML in {path}: {exc}",
        ) from exc
    if not isinstance(data, dict):
        raise AudiaGenticError(
            code="VAL-DESC-003",
            kind="descriptor",
            message=f"Descriptor file must contain a mapping at top level: {path}",
        )
    return data


def iter_descriptor_files(directory: Path) -> list[Path]:
    """Return sorted list of YAML files in a descriptor directory."""
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))


@dataclass
class DescriptorSpec:
    """Field map for a descriptor type.

    Maps Python field names to FieldSpec instances that declare how each
    field is loaded from YAML.

    Attributes:
        fields: Mapping from Python field name to FieldSpec.
        required_fields: List of field names that must be present.
        constructor: Callable that builds the final typed descriptor.
    """
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    constructor: Callable[..., Any] | None = None

    def add(self, name: str, yaml_key: str | None = None, **kwargs: Any) -> None:
        """Add a field specification."""
        self.fields[name] = FieldSpec(
            yaml_key=yaml_key or name.replace("_", "-"),
            **kwargs,
        )

    def load(self, data: dict[str, Any]) -> dict[str, Any]:
        """Load a descriptor from YAML data dict.

        Resolves refs, builds steps, constructs nested objects, and
        validates required fields.

        Args:
            data: Parsed YAML dictionary.

        Returns:
            Dict of resolved field values ready for constructor.

        Raises:
            AudiaGenticError: VAL-DESC-003 for missing required fields.
        """
        resolved = {}

        for field_name, spec in self.fields.items():
            yaml_key = spec.yaml_key
            raw = data.get(yaml_key)

            if raw is None:
                if spec.required:
                    raise AudiaGenticError(
                        code="VAL-DESC-003",
                        kind="descriptor",
                        message=f"Required field '{yaml_key}' missing from descriptor",
                    )
                resolved[field_name] = spec.default
                continue

            if spec.kind == "data":
                resolved[field_name] = spec.converter(raw) if spec.converter else raw
            elif spec.kind == "ref":
                resolved[field_name] = resolve_ref(str(raw))
            elif spec.kind == "step":
                # Lazy import: step building is workflow's deserializer; only
                # descriptor types that declare step fields pay for workflow.
                from audiagentic.foundation.workflow.invocation.from_spec import (
                    build_step_from_spec,
                )
                resolved[field_name] = build_step_from_spec(raw)
            elif spec.kind == "nested":
                if spec.builder:
                    resolved[field_name] = spec.builder(raw)
                else:
                    resolved[field_name] = raw
            else:
                resolved[field_name] = raw

        return resolved

    def build(self, data: dict[str, Any]) -> Any:
        """Load and construct a typed descriptor from YAML data.

        Args:
            data: Parsed YAML dictionary.

        Returns:
            Constructed descriptor instance.
        """
        resolved = self.load(data)
        if self.constructor:
            return self.constructor(**resolved)
        return resolved


def load_descriptor(path: Path, spec: DescriptorSpec) -> Any:
    """Load a typed descriptor from a YAML file.

    Args:
        path: Path to the YAML file.
        spec: Field specification for the descriptor type.

    Returns:
        Constructed descriptor instance.
    """
    data = _load_yaml_file(path)
    return spec.build(data)
