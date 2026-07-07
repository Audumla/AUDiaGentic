"""Provision step protocol, placeholder substitution, and step-type registry.

Every execution primitive implements the :class:`ProvisionStep` protocol with
a common ``run(context) / revert(context) / dry_run(context)`` interface.
Step kinds register a ``from_dict`` constructor via :func:`register_step_type`
at module import time; the factory is a pure registry lookup, so new step
kinds need no foundation edits (Standard 2).

This package lives in ``foundation/`` and MUST NOT import any ``components/``
types (S1 layering constraint).
"""
from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any, Protocol

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.registry_utils import Registry
from audiagentic.foundation.workflow.invocation.models import StepResult

from ..artifact_registry import ArtifactRegistry

_pstep_error = make_error_factory("VAL", "PSTEP", "provision-step")


class ProvisionStep(Protocol):
    """Common interface for all provisioning primitives."""

    id: str

    def run(self, context: dict[str, Any]) -> StepResult: ...
    def revert(self, context: dict[str, Any]) -> StepResult: ...
    def dry_run(self, context: dict[str, Any]) -> StepResult: ...


# from_dict(data, params, registry, recipe_id) -> ProvisionStep
StepFromDict = Callable[
    [dict[str, Any], dict[str, str], "ArtifactRegistry | None", "str | None"],
    ProvisionStep,
]

def _load_builtin_step_types() -> None:
    modules = {
        "shell": (
            "audiagentic.foundation.toolchains.provision_steps.shell",
            "_shell_from_dict",
        ),
        "config-set": (
            "audiagentic.foundation.toolchains.provision_steps.config_set",
            "_config_set_from_dict",
        ),
        "managed-block": (
            "audiagentic.foundation.toolchains.provision_steps.managed_block_step",
            "_managed_block_from_dict",
        ),
        "write-file": (
            "audiagentic.foundation.toolchains.provision_steps.write_file",
            "_write_file_from_dict",
        ),
    }
    for kind, (module_name, factory_name) in modules.items():
        module = importlib.import_module(module_name)
        register_step_type(kind, getattr(module, factory_name))


_STEP_TYPES: Registry[StepFromDict] = Registry(loader=_load_builtin_step_types)


def register_step_type(kind: str, from_dict: StepFromDict) -> None:
    """Register a step-kind constructor for provision_step_from_dict."""
    _STEP_TYPES.register(kind, from_dict, replace=True)


def registered_step_types() -> dict[str, StepFromDict]:
    return _STEP_TYPES.all()


def _substitute(value: Any, params: dict[str, str], path: str = "") -> Any:
    """Recursively substitute ``{KEY}`` placeholders in strings, lists, and dicts.

    Raises AudiaGenticError for unknown placeholders. Literal braces (not matching
    a known param key) are preserved as-is, so JSON content with structural
    braces is handled correctly.
    """
    import re as _re

    if isinstance(value, str):
        # Find all {WORD} patterns; validate against known params
        pattern = _re.compile(r'\{(\w+)\}')
        matches = pattern.findall(value)
        for match in matches:
            if match not in params:
                raise _pstep_error(
                    2,
                    f"unknown placeholder {{{match}}} at {path or 'root'}",
                    placeholder=match,
                    path=path,
                )
        # Perform substitution using str.format — safe because we validated keys
        try:
            return pattern.sub(lambda m: params[m.group(1)], value)
        except Exception:
            raise _pstep_error(
                2,
                f"substitution error at {path or 'root'}",
                path=path,
            )
    if isinstance(value, list):
        return [_substitute(item, params, f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {
            k: _substitute(v, params, f"{path}.{k}")
            for k, v in value.items()
        }
    return value
