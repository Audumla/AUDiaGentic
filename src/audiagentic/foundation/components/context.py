"""Pure validation and sanitisation for component template context."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.logging.redaction import is_sensitive_key

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


def sanitize_context_section(component_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
    """Return one bounded, redacted, JSON-compatible context section."""
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
