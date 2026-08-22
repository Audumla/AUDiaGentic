"""Generic, component-owned template context collection."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.logging.redaction import is_sensitive_key

from .hooks import _resolve_hook
from .registry import all_descriptors, is_enabled, is_installed

_MAX_SECTION_BYTES = 4 * 1024


def context_namespace(component_id: str, declared: str | None = None) -> str:
    """Return a stable dotted-template namespace for a component."""
    value = declared or component_id.replace("-", "_")
    if not value or not value.replace("_", "").isalnum():
        raise AudiaGenticError(
            code="VAL-COMP-001", kind="components",
            message="component context namespace must be alphanumeric with underscores",
            details={"component-id": component_id, "namespace": value},
        )
    return value


def _safe_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if not is_sensitive_key(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise AudiaGenticError(
        code="VAL-COMP-001", kind="components",
        message="component context values must be JSON-compatible scalars, mappings, or lists",
        details={"type": type(value).__name__},
    )


def _safe_section(component_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
    result = _safe_value(values)
    assert isinstance(result, dict)
    try:
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AudiaGenticError(
            code="VAL-COMP-001", kind="components",
            message="component context must be JSON-serializable",
            details={"component-id": component_id},
        ) from exc
    if len(encoded) > _MAX_SECTION_BYTES:
        raise AudiaGenticError(
            code="VAL-COMP-001", kind="components",
            message="component context exceeds the 4KB section limit",
            details={"component-id": component_id, "bytes": len(encoded)},
        )
    return result


def collect_component_context(project_root: Path) -> dict[str, dict[str, Any]]:
    """Collect safe context from installed and enabled component hooks.

    The foundation owns discovery and namespacing. Components own only the
    returned facts. Hook failures are deliberately fail-closed at admission.
    """
    collected: dict[str, dict[str, Any]] = {}
    for component_id, descriptor in all_descriptors().items():
        hook_path = descriptor.context_hook
        if not hook_path or not is_installed(component_id, project_root) or not is_enabled(component_id, project_root):
            continue
        hook = _resolve_hook(hook_path)
        if hook is None:
            raise AudiaGenticError(
                code="INT-COMP-002", kind="components",
                message="component context hook could not be resolved",
                details={"component-id": component_id, "hook": hook_path},
            )
        try:
            values = hook(project_root)
        except Exception as exc:  # noqa: BLE001 - configuration boundary
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
        collected[namespace] = _safe_section(component_id, values)
    return collected
