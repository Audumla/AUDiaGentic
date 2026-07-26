"""Dotpath reference resolver for declarative configuration.

Resolves ``module:dotpath`` references to live Python objects. Uses colon
separator to avoid ambiguity with Python attribute access. This is the single
canonical resolver (PD08 D1) — no second dotpath implementation may be added.

Callers pass ref strings sourced from config data (YAML descriptors, matrix
rows), keeping the binding declarative; hardcoding ref strings in Python code
defeats static analysis and is an anti-pattern — use a normal import instead.

Error codes:
    VAL-DESC-001 — module not found or attribute not found in resolved module
"""
from __future__ import annotations

import importlib
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError


def resolve_ref(ref: str) -> Any:
    """Resolve a ``module:dotpath`` reference to a live Python object.

    The ref format is ``module_path:object_name`` where *module_path* is a
    fully-qualified Python module (e.g. ``audiagentic.foundation.mcp.json_format``)
    and *object_name* is a top-level attribute of that module.

    For nested attributes within a module, use additional colons:
    ``module_path:submodule:object_name`` resolves to
    ``import module_path.submodule; module_path.submodule.object_name``.

    Args:
        ref: Colon-separated module:dotpath string.

    Returns:
        The resolved Python object (function, class, constant, etc.).

    Raises:
        AudiaGenticError: VAL-DESC-001 if module or attribute not found.
    """
    if not ref or ":" not in ref:
        raise AudiaGenticError(
            code="VAL-DESC-001",
            kind="descriptor",
            message=f"Invalid ref format (expected 'module:object'): {ref!r}",
        )

    parts = [p.strip() for p in ref.split(":")]
    module_path = parts[0]
    attr_path = parts[1:]

    try:
        obj = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise AudiaGenticError(
            code="VAL-DESC-001",
            kind="descriptor",
            message=f"Module not found for ref {ref!r}: {exc.name}",
        ) from exc

    for attr in attr_path:
        if not hasattr(obj, attr):
            raise AudiaGenticError(
                code="VAL-DESC-001",
                kind="descriptor",
                message=f"Attribute {attr!r} not found in {module_path}",
            )
        obj = getattr(obj, attr)

    return obj
