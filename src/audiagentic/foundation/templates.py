"""Dotted-path template renderer for prompt data values.

Resolves ``{dotted.path}`` placeholders inside prompt templates against a
mapping context. This is a pure, trigger-neutral mapping renderer: it receives
a context dict and returns rendered text. It never imports agent-jobs, planning,
events, or agents.

This mechanism resolves dotted DATA paths inside prompt templates. It is NOT
related to :func:`audiagentic.foundation.config.refs.resolve_ref`, which resolves
``module:object`` config references to live Python objects — those are entirely
unrelated mechanisms with different error codes and use cases.

Only identifier-shaped dotted paths are interpreted as placeholders. Literal
JSON and code braces are preserved, so prompt text such as
``Return exactly {"status": "ok"}`` does not require escaping.

It is also distinct from :func:`audiagentic.foundation.workflow.actions.render`
(EDJ21 decision): that renderer preserves typed whole-placeholder values and
uses full ``str.format`` semantics for mixed strings; this one always returns
a string and resolves dotted paths. Consolidating them was evaluated and
stopped — see ``tests/unit/foundation/test_actions_render_compat.py``.

Error codes:
    VAL-TPL-001 — placeholder path not found in context; message includes the
        missing path and available top-level keys for diagnostics.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

# Only dotted data paths are placeholders.  Prompt text frequently contains
# literal JSON/code braces (for example ``{"status": "ok"}``); treating every
# brace pair as a lookup made otherwise-valid prompts fail admission with a
# misleading missing-key error.  Keeping the grammar narrow also makes the
# template language deterministic: a placeholder starts with an identifier,
# then permits identifier/hyphen segments separated by dots.
_PLACEHOLDER_RE = re.compile(
    r"\{([A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*)\}"
)


class _Missing:
    """Sentinel distinguishing a missing path from a present ``None`` value."""

    def __repr__(self) -> str:  # pragma: no cover — diagnostics only
        return "<MISSING>"


# Exported for internal/foundation consumers only (e.g. trigger filter
# evaluation); never surfaced in configuration.
_MISSING = _Missing()


def has_placeholders(template: str) -> bool:
    """Return True when *template* contains at least one ``{...}`` placeholder."""
    return bool(_PLACEHOLDER_RE.search(template))


def resolve_path(context: Mapping[str, Any], path: str) -> Any:
    """Resolve a dotted path against nested mappings.

    Returns the resolved value (which may legitimately be ``None``) or the
    :data:`_MISSING` sentinel when any segment is absent. This is the single
    dotted-path lookup shared by template rendering and trigger filter
    evaluation — the two must never diverge.
    """
    current: Any = context
    for seg in path.split("."):
        if isinstance(current, Mapping) and seg in current:
            current = current[seg]
        else:
            return _MISSING
    return current


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
        value = resolve_path(ctx, path)
        if value is _MISSING:
            raise AudiaGenticError(
                code="VAL-TPL-001",
                kind="template",
                message=(
                    f"Template path {path!r} not found in context; "
                    f"available top-level keys: {', '.join(sorted(ctx.keys()))}"
                ),
                details={"path": path, "available_keys": sorted(ctx.keys())},
            )
        return value

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
