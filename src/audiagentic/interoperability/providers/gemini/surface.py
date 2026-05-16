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
                path=project_root / "GEMINI.md",
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
            render_flat_skill(
                skill,
                provider_name="gemini",
                launch_example=f"@{skill.tag}-gemini",
            )
        )

    surfaces[project_root / "GEMINI.md"] = apply_managed_header(
        "# GEMINI.md\n\n"
        "This repository uses AUDiaGentic workflow jobs.\n\n"
        "## Bridge\n\n"
        "When a prompt begins with a workflow tag, route it through the repo-owned bridge:\n\n"
        "```powershell\n"
        "python tools/gemini_prompt_trigger_bridge.py --project-root .\n"
        "```\n\n"
        "If a native hook path is present in the active Gemini build, it should normalize into the\n"
        "same shared launch contract. If it is not stable, the bridge stays authoritative.\n\n"
        "## Prompt tag doctrine\n\n"
        "- Parse only the first non-empty line for the workflow tag.\n"
        "- Keep tag semantics identical to the shared AUDiaGentic launch contract.\n"
        "- Do not invent provider-specific alternate tags.\n"
        "- Preserve raw prompt text in provenance metadata.\n"
        "- Keep provenance visible: provider id, surface, and session id should survive normalization.\n"
    )
    return surfaces


register_renderer("gemini", render)
register_contribution_renderer("gemini", render_contributions)
