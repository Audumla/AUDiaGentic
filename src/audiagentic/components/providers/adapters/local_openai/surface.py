"""Local OpenAI surface handler — raises for unsupported surface operations.

OpenAI-compatible endpoints are API-only passthroughs. They do not support
MCP servers, LSP projections, skill surfaces, instruction files, or agent
file contributions. Any attempt to access these features through the provider
infrastructure raises an AudiaGenticError.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

from ...surfaces.base import (
    SkillDefinition,
    SurfaceBlock,
    SurfaceContribution,
)
from ...surfaces.registry import register_contribution_renderer, register_renderer


def _raise_unsupported(feature: str) -> None:
    raise AudiaGenticError(
        code="UNS-OPENAI-001",
        kind="providers",
        message=f"local-openai does not support {feature}. OpenAI-compatible endpoints are API-only passthroughs.",
        details={"provider-id": "local-openai", "feature": feature},
    )


def render(
    *,
    project_root: Path,
    syntax: dict[str, Any],
    skills: list[SkillDefinition],
    config: dict[str, Any],
) -> dict[Path, str]:
    _raise_unsupported("skill surfaces and instruction files")
    return {}


def render_contributions(
    *,
    project_root: Path,
    contributions: list[SurfaceContribution],
) -> list[SurfaceBlock]:
    _raise_unsupported("provider surface contributions")
    return []


register_renderer("local-openai", render)
register_contribution_renderer("local-openai", render_contributions)
