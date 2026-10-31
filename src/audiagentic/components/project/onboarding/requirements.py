"""Owner-schema configuration preflight; no alternate options authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.features.loader import read_implementation_metadata
from audiagentic.foundation.features.options import option_schema_to_dict, resolve_options
from audiagentic.foundation.features.registry import resolve_active_implementation
from audiagentic.foundation.features.state import get_component_state, set_component_state
from audiagentic.foundation.io import load_yaml_file
from audiagentic.foundation.logging.redaction import is_sensitive_key

from .catalog import error


def describe(root: Path | None, component_id: str) -> list[dict]:
    """Read schema-derived help without resolving or migrating runtime state."""
    return [
        {
            "implementation_id": item.implementation_id,
            "fields": {
                key: {
                    k: v
                    for k, v in option_schema_to_dict(field).items()
                    if k != "default" or not is_sensitive_key(key)
                }
                for key, field in item.options_schema.items()
            },
        }
        for item in read_implementation_metadata(root)
        if item.parent == component_id
    ]


def resolve(
    root: Path, owner, config_file: Path | None, *, interactive: bool = False
) -> dict[str, Any]:
    state = get_component_state(root, owner.component_id)
    supplied = load_yaml_file(config_file) if config_file else {}
    if set(supplied) - {"options"} or not isinstance(supplied.get("options", {}), dict):
        raise error("Configuration file must contain an owner options mapping")
    options = supplied.get("options", {})
    selected = state.get("implementations", {})
    implementations = {
        d.implementation_id: d
        for d in read_implementation_metadata(root)
        if d.parent == owner.component_id
    }
    active = resolve_active_implementation(
        root, owner.component_id, implementation_descriptors=implementations, component_state=state
    )
    schemas = implementations[active].options_schema if active in implementations else {}
    if set(options) - set(schemas):
        raise error("Configuration contains unsupported owner option keys")
    if any(is_sensitive_key(key) for key in options):
        raise error("Configure sensitive values through the owning secure configuration interface")
    # Implementation-specific state remains the higher-precedence owner layer.
    impl_options = {
        k: v for k, v in selected.get(active, {}).get("options", {}).items() if k in schemas
    }
    values = resolve_options(
        schemas,
        {k: v for k, v in state.get("options", {}).items() if k in schemas},
        options,
        impl_options,
    )
    missing = [key for key, field in schemas.items() if field.required and key not in values]
    if interactive:
        import json

        for key in tuple(missing):
            if is_sensitive_key(key):
                continue
            answer = input(f"{key}: {schemas[key].description}: ")
            options[key] = (
                answer
                if schemas[key].option_type in {"str", "string", "enum"}
                else json.loads(answer)
            )
        values = resolve_options(schemas, values, options)
        missing = [key for key, field in schemas.items() if field.required and key not in values]
    if missing:
        raise error("Required owner configuration is missing", missing_keys=missing)
    return {"options": options, "state": state, "values": values}


def persist(root: Path, component_id: str, resolution: dict) -> bool:
    if resolution["options"]:
        validate_current(root, component_id, resolution)
        state = resolution["state"]
        options = {**state.get("options", {}), **resolution["options"]}
        if options != state.get("options", {}):
            set_component_state(root, component_id, {**state, "options": options})
            return True
    return False


def validate_current(root: Path, component_id: str, resolution: dict) -> None:
    if get_component_state(root, component_id) != resolution["state"]:
        raise error("Owner configuration changed after preflight; retry the installation")
