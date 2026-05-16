from __future__ import annotations

from pathlib import Path
from typing import Any

from ..surfaces.base import (
    SkillDefinition,
    SurfaceBlock,
    SurfaceContribution,
    apply_managed_header,
    render_flat_skill,
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

    surfaces[project_root / ".clinerules" / "prompt-tags.md"] = apply_managed_header(
        "# Prompt tag doctrine\n\n"
        "Rules:\n\n"
        "- Parse only the first non-empty line for the workflow tag.\n"
        "- Keep tag semantics identical to the shared AUDiaGentic launch contract.\n"
        "- Do not invent provider-specific alternate tags.\n"
        "- Preserve raw prompt text in provenance metadata.\n"
        "- Route tagged prompts through the shared bridge when a native hook path is not stable.\n"
        "- Canonical names are config-managed in `.audiagentic/config/execution/prompt-syntax.yaml`;\n"
        "  run `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases.\n"
    )
    return surfaces


register_renderer("cline", render)
register_contribution_renderer("cline", render_contributions)
