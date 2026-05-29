from __future__ import annotations

from pathlib import Path
from typing import Any

from ...surfaces.base import (
    SkillDefinition,
    SurfaceBlock,
    SurfaceContribution,
    apply_managed_header,
    render_flat_skill,
    render_rules_file,
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
        blocks.append(
            SurfaceBlock(
                path=project_root / ".clinerules" / "audiagentic.md",
                block_id=contribution.contribution_id,
                content=f"# {contribution.title}\n\n{contribution.body.strip()}",
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
            render_flat_skill(
                skill,
                provider_name="cline",
                launch_example=f"@{skill.tag}-cline",
            )
        )

    surfaces[project_root / ".clinerules" / "prompt-tags.md"] = render_rules_file(
        adapter_dir=_ADAPTER_DIR,
    )
    return surfaces


register_renderer("cline", render)
register_contribution_renderer("cline", render_contributions)
