"""Feature intent: what the user decided, read from and written to settings.

``features.<component>.implementations.<id>.{enabled,options,features.<kind:id>}`` and
``features.<component>.features.<kind:id>`` in ``settings.yaml``. Reads are effective values
across scopes with the three-way answer the old shard gave: ``None`` (never decided),
``False`` and ``True``. Writes are sparse RFC 7396 patches through ``write_settings_patch``,
serialized and validated there. Observations (availability, outcomes) do not belong here; see
``observations``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.config.settings import resolve_settings_cached
from audiagentic.foundation.config.writer import WriteResult, write_settings_patch

from .state import feature_composite_key

SECTION = "features"


def _node(project_root: Path | None, path: tuple[str, ...]) -> Any:
    node: Any = resolve_settings_cached(project_root).get(SECTION)
    for part in path:
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _tri_state(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def implementation_path(component: str, implementation: str) -> tuple[str, ...]:
    return (component, "implementations", implementation)


def feature_path(
    component: str, kind: str, feature_id: str, implementation: str | None = None,
) -> tuple[str, ...]:
    base = (component,) if implementation is None else implementation_path(component, implementation)
    return (*base, "features", feature_composite_key(kind, feature_id))


def implementation_enabled(project_root: Path | None, component: str, implementation: str) -> bool | None:
    return _tri_state((_node(project_root, implementation_path(component, implementation)) or {}).get("enabled"))


def implementation_options(project_root: Path | None, component: str, implementation: str) -> dict[str, Any]:
    options = (_node(project_root, implementation_path(component, implementation)) or {}).get("options")
    return dict(options) if isinstance(options, dict) else {}


def feature_enabled(
    project_root: Path | None, component: str, kind: str, feature_id: str, implementation: str | None = None,
) -> bool | None:
    return _tri_state((_node(project_root, feature_path(component, kind, feature_id, implementation)) or {}).get("enabled"))


def feature_options(
    project_root: Path | None, component: str, kind: str, feature_id: str, implementation: str | None = None,
) -> dict[str, Any]:
    options = (_node(project_root, feature_path(component, kind, feature_id, implementation)) or {}).get("options")
    return dict(options) if isinstance(options, dict) else {}


def _patch(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    patch: Any = value
    for part in reversed((SECTION, *path)):
        patch = {part: patch}
    return patch


def set_intent(
    path: tuple[str, ...], value: Any, *, project_root: Path, scope: str = "project", dry_run: bool = False,
) -> WriteResult:
    """Set one intent key (``value`` ``None`` clears it back to "never decided")."""
    return write_settings_patch(scope, _patch(path, value), project_root=project_root, dry_run=dry_run)


def set_implementation_enabled(
    project_root: Path, component: str, implementation: str, enabled: bool | None, *, scope: str = "project",
) -> WriteResult:
    return set_intent((*implementation_path(component, implementation), "enabled"), enabled,
                      project_root=project_root, scope=scope)


def set_feature_enabled(
    project_root: Path, component: str, kind: str, feature_id: str, enabled: bool | None,
    *, implementation: str | None = None, scope: str = "project",
) -> WriteResult:
    return set_intent((*feature_path(component, kind, feature_id, implementation), "enabled"), enabled,
                      project_root=project_root, scope=scope)
