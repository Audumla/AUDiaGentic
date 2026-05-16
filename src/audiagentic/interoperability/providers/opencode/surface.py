from __future__ import annotations

from pathlib import Path
from typing import Any

from ..surfaces.base import (
    SkillDefinition,
    SurfaceBlock,
    SurfaceContribution,
    apply_managed_header,
    render_frontmatter_skill,
    resolve_tag_path,
)
from ..surfaces.registry import register_contribution_renderer, register_renderer


def render_contributions(
    *,
    project_root: Path,
    contributions: list[SurfaceContribution],
) -> list[SurfaceBlock]:
    blocks: list[SurfaceBlock] = []
    for contribution in contributions:
        if contribution.kind != "rule":
            continue
        blocks.append(
            SurfaceBlock(
                path=project_root / "AGENTS.md",
                block_id=contribution.contribution_id,
                content=f"## {contribution.title}\n\n{contribution.body.strip()}",
            )
        )
    return blocks


def render(
    *,
    project_root: Path,
    syntax: dict[str, Any],
    skills: list[SkillDefinition],
    config: dict[str, Any],
) -> dict[Path, str]:
    del syntax
    surfaces: dict[Path, str] = {}
    path_template = str(config["path"])
    for skill in skills:
        path = resolve_tag_path(project_root, path_template, skill.tag)
        surfaces[path] = apply_managed_header(
            render_frontmatter_skill(skill, root_label=path_template.format(tag=skill.tag))
        )
    return surfaces


register_renderer("opencode", render)
register_contribution_renderer("opencode", render_contributions)
