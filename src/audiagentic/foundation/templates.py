"""Dotted-path template renderer for prompt data values.

Resolves ``{dotted.path}`` placeholders inside prompt templates against a
mapping context. This is a pure, trigger-neutral mapping renderer: it receives
a context dict and returns rendered text. It never imports agent-jobs, planning,
events, or agents.

This mechanism resolves dotted DATA paths inside prompt templates. It is NOT
related to :func:`audiagentic.foundation.refs.resolve_ref`, which resolves
``module:object`` config references to live Python objects — those are entirely
unrelated mechanisms with different error codes and use cases.

Error codes:
    VAL-TPL-001 — placeholder path not found in context; message includes the
        missing path and available top-level keys for diagnostics.
"""
from __future__ import annotations

import re
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

_PLACEHOLDER_RE = re.compile(r"\{([^}]+)\}")


def render_template(template: str, context: dict[str, Any]) -> str:
    """Render a dotted-path template against a context mapping.

    Replaces ``{dotted.path}`` placeholders using recursive dict lookup.
    Supports nested paths like ``{event.payload.id}``, hyphenated keys
    (``{metadata.correlation-id}``), and mixed literal + placeholder text.

    If the value at a resolved path is not a string, it is converted via
    ``str()`` for whole-placeholder replacement. Missing keys raise
    :class:`~audiagentic.foundation.contracts.errors.AudiaGenticError` with
    code VAL-TPL-001.

    Args:
        template: Template string with ``{...}`` placeholders.
        context: Mapping of top-level keys to values. Nested dicts support
            dotted path lookup.

    Returns:
        The rendered string with all placeholders replaced.

    Raises:
        AudiaGenticError: VAL-TPL-001 if a placeholder path is not found in
            the context. Includes the missing path and available top-level keys.
    """
    def _resolve(path: str, ctx: dict[str, Any]) -> Any:
        segments = path.split(".")
        current: Any = ctx
        for seg in segments:
            if isinstance(current, dict) and seg in current:
                current = current[seg]
            else:
                raise AudiaGenticError(
                    code="VAL-TPL-001",
                    kind="template",
                    message=(
                        f"Template path {path!r} not found in context; "
                        f"available top-level keys: {', '.join(sorted(ctx.keys()))}"
                    ),
                    details={"path": path, "available_keys": sorted(ctx.keys())},
                )
        return current

    def _replace(match: re.Match[str]) -> str:
        path = match.group(1).strip()
        value = _resolve(path, context)
        if value is None:
            return ""
        if isinstance(value, dict) or isinstance(value, list):
            import json
            return json.dumps(value)
        return str(value)

    return _PLACEHOLDER_RE.sub(_replace, template)
