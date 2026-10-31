"""The ``harness`` settings section, as the views the harness and Pi code read.

Everything comes from the resolved settings (vendor defaults, then user, then project), so each
value carries provenance and ``audiagentic config show harness`` explains it. With no project the
project scope is skipped, as it was for the layered files this replaces.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from .settings import resolve_settings_cached

SECTION = "harness"


def harness_section(project_root: Path | None = None) -> dict[str, Any]:
    resolved = (
        resolve_settings_cached(project_root) if project_root is not None
        else resolve_settings_cached(machine_only=True)
    )
    section = resolved.get(SECTION)
    return deepcopy(section) if isinstance(section, dict) else {}


def harness_ag_config(project_root: Path | None = None) -> dict[str, Any]:
    """The generic harness view: ``harness`` (order, type), ``endpoint``, ``smoke``, ``mcp``."""
    section = harness_section(project_root)
    config: dict[str, Any] = {"harness": {key: section[key] for key in ("order", "type") if key in section}}
    for key in ("endpoint", "smoke", "mcp"):
        if key in section:
            config[key] = section[key]
    return config


def harness_pi_config(project_root: Path | None = None) -> dict[str, Any]:
    """The Pi view: ``agent``, ``tools``, ``lockdown``, ``ui``."""
    pi = harness_section(project_root).get("pi")
    return pi if isinstance(pi, dict) else {}


__all__ = ["SECTION", "harness_ag_config", "harness_pi_config", "harness_section"]
