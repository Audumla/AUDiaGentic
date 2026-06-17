"""Propagation config loader, validator, and rule-importer."""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def load_config(path: Path | None) -> dict[str, Any]:
    """Load a propagation YAML config.

    Returns a disabled config if the path is missing or invalid — propagation
    behaviour must be explicit, never implicit.
    """
    if path is None or not path.exists():
        if path is not None:
            logger.warning("Propagation config not found at %s. Propagation disabled.", path)
        return {"global": {"enabled": False}}

    try:
        with path.open(encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except Exception:
        logger.error("Failed to load propagation config. Propagation disabled.", exc_info=True)
        return {"global": {"enabled": False}}

    bind_callables(config)
    return config


def bind_callables(config: dict[str, Any]) -> None:
    """Resolve ``logic:`` references on rules and actions into real callables."""
    for section in ("rules", "actions"):
        entries = config.get(section, {})
        for name, entry in entries.items():
            logic = entry.get("logic")
            if callable(logic):
                continue
            if isinstance(logic, str):
                try:
                    entry["logic"] = _import_callable(logic)
                except (ImportError, AttributeError, ValueError) as exc:
                    raise ValueError(f"Failed to load {section} {name}: {exc}") from exc


def _import_callable(ref: str) -> Callable:
    module_name, _, func_name = ref.rpartition(".")
    if not module_name or not func_name:
        raise ValueError(f"Invalid callable reference: {ref}")
    module = importlib.import_module(module_name)
    func = getattr(module, func_name)
    if not callable(func):
        raise AttributeError(f"{ref} is not callable")
    return func


def validate(config: dict[str, Any], states_for_kind: Callable[[str], list[str]] | None) -> list[str]:
    """Return a list of validation warnings (empty when valid)."""
    errors: list[str] = []
    validation_rules = config.get("validation", {})

    for field_path in validation_rules.get("required_fields", []):
        node: Any = config
        for part in field_path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                errors.append(f"Missing required field: {field_path}")
                break

    rules = config.get("rules", {})
    for rule_name in validation_rules.get("required_rules", []):
        if rule_name not in rules:
            errors.append(f"Missing required rule: {rule_name}")

    kinds = config.get("kinds", {})
    if states_for_kind is not None:
        for kind_name, kind_config in kinds.items():
            if kind_config.get("enabled") is False:
                continue
            try:
                valid_states = set(states_for_kind(kind_name))
            except (KeyError, TypeError):
                valid_states = set()
            for state in kind_config.get("state_rules", {}):
                if state not in valid_states:
                    errors.append(f"Invalid state '{state}' in kind '{kind_name}'")

    configured_rules = set(rules.keys())
    for kind_name, kind_config in kinds.items():
        if kind_config.get("enabled") is False:
            continue
        for state, state_config in kind_config.get("state_rules", {}).items():
            rule = state_config.get("rule")
            if rule and rule not in configured_rules:
                errors.append(
                    f"Invalid rule '{rule}' for state '{state}' in kind '{kind_name}'"
                )

    return errors
