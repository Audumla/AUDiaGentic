"""Runtime orchestration for descriptor-declared component template context."""
from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from audiagentic.foundation.components.context import (
    context_namespace,
    sanitize_context_section,
)
from audiagentic.foundation.components.registry import (
    all_descriptors,
    is_enabled,
    is_installed,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

ContextHook = Callable[[Path], Mapping[str, Any] | None]


def _resolve_context_hook(path: str) -> ContextHook:
    module_name, separator, function_name = path.rpartition(".")
    if not separator or not module_name or not function_name:
        raise AudiaGenticError(
            code="INT-COMP-002", kind="components",
            message="component context hook has an invalid dotted path",
            details={"hook": path},
        )
    try:
        hook = getattr(importlib.import_module(module_name), function_name, None)
    except Exception as exc:  # noqa: BLE001 - configured runtime boundary
        raise AudiaGenticError(
            code="INT-COMP-002", kind="components",
            message="component context hook could not be resolved",
            details={"hook": path},
        ) from exc
    if not callable(hook):
        raise AudiaGenticError(
            code="INT-COMP-002", kind="components",
            message="component context hook could not be resolved",
            details={"hook": path},
        )
    return hook


def collect_component_context(project_root: Path) -> dict[str, dict[str, Any]]:
    """Invoke enabled component context surfaces and return safe facts."""
    collected: dict[str, dict[str, Any]] = {}
    for component_id, descriptor in all_descriptors().items():
        hook_path = descriptor.context_hook
        if not hook_path or not is_installed(component_id, project_root) or not is_enabled(component_id, project_root):
            continue
        hook = _resolve_context_hook(hook_path)
        try:
            values = hook(project_root)
        except Exception as exc:  # noqa: BLE001 - configured runtime boundary
            raise AudiaGenticError(
                code="INT-COMP-002", kind="components",
                message="component context hook failed",
                details={"component-id": component_id, "hook": hook_path},
            ) from exc
        if values is None:
            continue
        if not isinstance(values, Mapping):
            raise AudiaGenticError(
                code="VAL-COMP-001", kind="components",
                message="component context hook must return a mapping or None",
                details={"component-id": component_id},
            )
        namespace = context_namespace(component_id, descriptor.context_namespace)
        if namespace in collected:
            raise AudiaGenticError(
                code="VAL-COMP-001", kind="components",
                message="duplicate component context namespace",
                details={"component-id": component_id, "namespace": namespace},
            )
        collected[namespace] = sanitize_context_section(component_id, values)
    return collected


__all__ = ["ContextHook", "collect_component_context"]
