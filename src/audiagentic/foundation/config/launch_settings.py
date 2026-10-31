"""Launch-time behaviour switches and the locale, read from the resolved settings.

``launch.status`` prints startup status lines, ``launch.auto_update`` checks for a newer release,
``launch.reconcile_providers`` decides whether launch re-detects provider CLIs (``auto`` runs it once
per project, ``always``/``never`` override that), and ``locale`` picks the message catalog. Unreadable
settings fall back to the defaults: a launch must not fail because a switch could not be read.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

from .settings import resolve_settings_cached

_DEFAULTS: dict[str, Any] = {"status": True, "auto_update": True, "reconcile_providers": "auto"}


def _resolved(project_root: Path | None) -> Any:
    return resolve_settings_cached(project_root) if project_root is not None else resolve_settings_cached(machine_only=True)


def launch_setting(name: str, project_root: Path | None = None) -> Any:
    try:
        section = _resolved(project_root).get("launch")
    except AudiaGenticError:
        return _DEFAULTS[name]
    value = section.get(name) if isinstance(section, dict) else None
    return _DEFAULTS[name] if value is None else value


def locale_setting(project_root: Path | None = None) -> str:
    try:
        value = _resolved(project_root).get("locale")
    except AudiaGenticError:
        return "en"
    return value if isinstance(value, str) and value else "en"


__all__ = ["launch_setting", "locale_setting"]
