from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory

from .base import OptionSchema

_option_error: Any = make_error_factory("VAL", "FOPT", "feature-options")


@dataclass(frozen=True)
class ResolvedOption:
    """Tracks the resolved value and its source layer for provenance debugging."""
    value: Any
    source: str  # 'schema-default' | 'component-state' | 'feature-state' | 'implementation-state'


def option_schema_from_mapping(data: dict[str, Any]) -> OptionSchema:
    return OptionSchema(
        option_type=str(data.get("type", "string")),
        default=data.get("default"),
        values=tuple(data.get("values") or ()),
        minimum=data.get("min"),
        maximum=data.get("max"),
        allow_unknown=bool(data.get("allow-unknown", False)),
        required=bool(data.get("required", False)),
        description=str(data.get("description", "")),
    )


def load_option_schema(raw: Any) -> dict[str, OptionSchema]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise _option_error(1, "options-schema must be a mapping", value_type=type(raw).__name__)
    result: dict[str, OptionSchema] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise _option_error(2, "option keys must be non-empty strings", key=key)
        if not isinstance(value, dict):
            raise _option_error(3, f"{key}: option schema must be a mapping", option=key)
        result[key] = option_schema_from_mapping(value)
    return result


def _validate_type(key: str, value: Any, schema: OptionSchema) -> None:
    expected = schema.option_type
    checks = {
        "bool": lambda v: isinstance(v, bool),
        "boolean": lambda v: isinstance(v, bool),
        "string": lambda v: isinstance(v, str),
        "str": lambda v: isinstance(v, str),
        "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "enum": lambda _v: True,
        "list": lambda v: isinstance(v, list),
        "object": lambda v: isinstance(v, dict),
    }
    check = checks.get(expected)
    if check is None:
        raise _option_error(4, f"{key}: unsupported option type {expected!r}", option=key, option_type=expected)
    if not check(value):
        raise _option_error(
            5,
            f"{key}: expected {expected}, got {type(value).__name__}",
            option=key,
            expected=expected,
            actual=type(value).__name__,
        )


def validate_option(key: str, value: Any, schema: OptionSchema) -> None:
    _validate_type(key, value, schema)
    if schema.option_type == "enum" and schema.values and value not in schema.values:
        allowed = ", ".join(str(v) for v in schema.values)
        raise _option_error(6, f"{key}: expected one of {allowed}, got {value!r}", option=key, allowed=schema.values)
    if schema.minimum is not None and value < schema.minimum:
        raise _option_error(7, f"{key}: must be >= {schema.minimum}", option=key, minimum=schema.minimum)
    if schema.maximum is not None and value > schema.maximum:
        raise _option_error(8, f"{key}: must be <= {schema.maximum}", option=key, maximum=schema.maximum)


def resolve_options(
    schema: dict[str, OptionSchema],
    *layers: dict[str, Any],
    reject_unknown: bool = True,
    layer_names: list[str] | None = None,
) -> dict[str, Any]:
    resolved = {
        key: option.default
        for key, option in schema.items()
        if option.default is not None
    }
    for layer in layers:
        for key, value in layer.items():
            if key not in schema:
                if reject_unknown:
                    raise _option_error(9, f"{key}: unknown option", option=key)
                resolved[key] = value
                continue
            validate_option(key, value, schema[key])
            resolved[key] = value
    return resolved


def resolve_options_with_provenance(
    schema: dict[str, OptionSchema],
    *layers: dict[str, Any],
    reject_unknown: bool = True,
    layer_names: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, ResolvedOption]]:
    """Resolve options and track which layer provided each value.

    Returns (resolved_dict, provenance_map). The provenance map keys are option
    names and values are ResolvedOption(value, source) where source is the layer
    name that last set the value.

    Layer names default to 'schema-default' for defaults, then 'layer-0', 'layer-1',
    etc. Pass explicit layer_names for meaningful labels like 'component-state',
    'feature-state', 'implementation-state'.
    """
    if layer_names is None:
        layer_names = [f"layer-{i}" for i in range(len(layers))]

    provenance: dict[str, ResolvedOption] = {}

    # Seed with schema defaults
    for key, option in schema.items():
        if option.default is not None:
            provenance[key] = ResolvedOption(value=option.default, source="schema-default")

    resolved = {k: v.value for k, v in provenance.items()}
    for i, layer in enumerate(layers):
        layer_name = layer_names[i] if i < len(layer_names) else f"layer-{i}"
        for key, value in layer.items():
            if key not in schema:
                if reject_unknown:
                    raise _option_error(9, f"{key}: unknown option", option=key)
                resolved[key] = value
                provenance[key] = ResolvedOption(value=value, source=layer_name)
                continue
            validate_option(key, value, schema[key])
            resolved[key] = value
            provenance[key] = ResolvedOption(value=value, source=layer_name)

    return resolved, provenance
