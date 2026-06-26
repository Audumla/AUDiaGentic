from __future__ import annotations

from pathlib import Path
from typing import Any

from ...surfaces.base import (
    SkillDefinition,
    SurfaceBlock,
    SurfaceContribution,
    apply_managed_header,
    is_component_active,
    render_frontmatter_skill,
    render_instruction_file,
    resolve_tag_path,
)
from ...surfaces.registry import register_contribution_renderer, register_renderer

_ADAPTER_DIR = Path(__file__).parent


def render_contributions(
    *,
    project_root: Path,
    contributions: list[SurfaceContribution],
) -> list[SurfaceBlock]:
    blocks: list[SurfaceBlock] = []
    for contribution in contributions:
        if "rule" in contribution.preferred_targets:
            filename = contribution.contribution_id.split("/")[-1]
            path = project_root / ".claude" / "rules" / f"{filename}.md"
            content = contribution.body.strip()
        else:
            path = project_root / "CLAUDE.md"
            content = f"## {contribution.title}\n\n{contribution.body.strip()}"
        blocks.append(SurfaceBlock(path=path, block_id=contribution.contribution_id, content=content))
    return blocks


def render(
    *,
    project_root: Path,
    syntax: dict[str, Any],
    skills: list[SkillDefinition],
    config: dict[str, Any],
) -> dict[Path, str]:
    del syntax  # unused by claude renderer
    surfaces: dict[Path, str] = {}
    path_template = str(config["path"])

    for skill in skills:
        path = resolve_tag_path(project_root, path_template, skill.tag)
        surfaces[path] = apply_managed_header(
            render_frontmatter_skill(skill, root_label=path_template.format(tag=skill.tag))
        )

    if is_component_active(project_root, "agent-jobs"):
        surfaces[project_root / "CLAUDE.md"] = render_instruction_file(
            provider_id="claude",
            instruction_file="CLAUDE.md",
            adapter_dir=_ADAPTER_DIR,
        )
    return surfaces


register_renderer("claude", render)
register_contribution_renderer("claude", render_contributions)
