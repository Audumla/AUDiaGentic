"""Hindsight provider recipe matrix — source-backed integration data.

This module loads the Hindsight recipe matrix from a YAML config file so
provider integration data is maintainable without code changes. The config
file lives at ``config/components/memory/hindsight_matrix.yaml``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

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
    install_command: str = ""
    uninstall_command: str = ""
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


_RECIPE_KIND_MAP = {
    "hooks": ProviderRecipeKind.HOOKS,
    "plugin_config": ProviderRecipeKind.PLUGIN_CONFIG,
    "mcp_config": ProviderRecipeKind.MCP_CONFIG,
    "wrapper_cli": ProviderRecipeKind.WRAPPER_CLI,
    "hybrid": ProviderRecipeKind.HYBRID,
    "guidance_only": ProviderRecipeKind.GUIDANCE_ONLY,
    "command_installer": ProviderRecipeKind.COMMAND_INSTALLER,
    "rules": ProviderRecipeKind.RULES,
    "context_provider": ProviderRecipeKind.CONTEXT_PROVIDER,
    "native_passthrough": ProviderRecipeKind.NATIVE_PASSTHROUGH,
}


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
        recipe_kind = _RECIPE_KIND_MAP.get(kind_str, ProviderRecipeKind.GUIDANCE_ONLY)
        rows.append(HindsightRecipeRow(
            provider_id=entry.get("provider_id", ""),
            display_name=entry.get("display_name", ""),
            integration_type=entry.get("integration_type", ""),
            recipe_kind=recipe_kind,
            install_command=entry.get("install_command", ""),
            uninstall_command=entry.get("uninstall_command", ""),
            status_command=entry.get("status_command", ""),
            config_artifacts=entry.get("config_artifacts", []),
            platform_constraints=entry.get("platform_constraints", []),
            scope=entry.get("scope", "project-local"),
            source_status=entry.get("source_status", "unconfirmed"),
            audia_action=entry.get("audia_action", "action_needed"),
            source_url=entry.get("source_url", ""),
            source_date=entry.get("source_date", ""),
            notes=entry.get("notes", ""),
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
