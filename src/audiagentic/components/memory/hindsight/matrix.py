"""Hindsight provider recipe matrix — source-backed integration data.

This module loads the Hindsight recipe matrix from a YAML config file so
provider integration data is maintainable without code changes. The config
file lives at ``config/components/memory/hindsight_matrix.yaml``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
)

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "components" / "memory" / "hindsight_matrix.yaml"


@dataclass(frozen=True)
class HindsightRecipeRow:
    """One row in the Hindsight provider recipe matrix."""

    provider_id: str
    display_name: str
    integration_type: str
    recipe_kind: ProviderRecipeKind
    install_steps: list[dict[str, Any]] = field(default_factory=list)
    uninstall_steps: list[dict[str, Any]] = field(default_factory=list)
    configure_steps: list[dict[str, Any]] = field(default_factory=list)
    status_command: str = ""
    config_artifacts: list[str] = field(default_factory=list)
    platform_constraints: list[str] = field(default_factory=list)
    scope: Literal["project-local", "global", "both"] = "project-local"
    source_status: Literal["verified", "unconfirmed", "blocked", "no_hindsight"] = "unconfirmed"
    audia_action: Literal[
        "call_official_installer",
        "manage_config_writes",
        "action_needed",
        "no_source",
    ] = "action_needed"
    source_url: str = ""
    source_date: str = ""
    notes: str = ""
    plugin_url_config_path: str = ""
    plugin_array_package: str = ""
    plugin_array_reader: str = ""
    plugin_array_writer: str = ""
    plugin_array_remover: str = ""
    # Plugin repair metadata (Windows-specific): empty values are no-ops
    plugin_repair_cache_pattern: str = ""
    plugin_repair_data_dir: str = ""
    plugin_repair_venv_python: str = ""
    plugin_repair_server_script: str = ""


def _load_matrix() -> list[HindsightRecipeRow]:
    """Load the Hindsight recipe matrix from YAML config."""
    if not _CONFIG_PATH.exists():
        return []

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "matrix" not in data:
        return []

    rows: list[HindsightRecipeRow] = []
    for entry in data["matrix"]:
        kind_str = entry.get("recipe_kind", "guidance_only")
        try:
            recipe_kind = ProviderRecipeKind(kind_str)
        except ValueError:
            recipe_kind = ProviderRecipeKind.GUIDANCE_ONLY
        rows.append(HindsightRecipeRow(
            provider_id=entry.get("provider_id", ""),
            display_name=entry.get("display_name", ""),
            integration_type=entry.get("integration_type", ""),
            recipe_kind=recipe_kind,
            install_steps=entry.get("install_steps", []),
            uninstall_steps=entry.get("uninstall_steps", []),
            configure_steps=entry.get("configure_steps", []),
            status_command=entry.get("status_command", ""),
            config_artifacts=entry.get("config_artifacts", []),
            platform_constraints=entry.get("platform_constraints", []),
            scope=entry.get("scope", "project-local"),
            source_status=entry.get("source_status", "unconfirmed"),
            audia_action=entry.get("audia_action", "action_needed"),
            source_url=entry.get("source_url", ""),
            source_date=entry.get("source_date", ""),
            notes=entry.get("notes", ""),
            plugin_url_config_path=entry.get("plugin_url_config_path", ""),
            plugin_array_package=entry.get("plugin_array_package", ""),
            plugin_array_reader=entry.get("plugin_array_reader", ""),
            plugin_array_writer=entry.get("plugin_array_writer", ""),
            plugin_array_remover=entry.get("plugin_array_remover", ""),
            plugin_repair_cache_pattern=entry.get("plugin_repair_cache_pattern", ""),
            plugin_repair_data_dir=entry.get("plugin_repair_data_dir", ""),
            plugin_repair_venv_python=entry.get("plugin_repair_venv_python", ""),
            plugin_repair_server_script=entry.get("plugin_repair_server_script", ""),
        ))
    return rows


# Module-level matrix — loaded once from config
HINDSIGHT_RECIPE_MATRIX: list[HindsightRecipeRow] = _load_matrix()


def get_matrix_rows() -> list[HindsightRecipeRow]:
    """Return the full Hindsight recipe matrix."""
    return list(HINDSIGHT_RECIPE_MATRIX)


def get_rows_for_provider(provider_id: str) -> list[HindsightRecipeRow]:
    """Return matrix rows for a specific provider."""
    return [row for row in HINDSIGHT_RECIPE_MATRIX if row.provider_id == provider_id]


def get_rows_by_kind(kind: ProviderRecipeKind) -> list[HindsightRecipeRow]:
    """Return matrix rows matching a recipe kind."""
    return [row for row in HINDSIGHT_RECIPE_MATRIX if row.recipe_kind == kind]


__all__ = [
    "HINDSIGHT_RECIPE_MATRIX",
    "HindsightRecipeRow",
    "get_matrix_rows",
    "get_rows_for_provider",
    "get_rows_by_kind",
]
