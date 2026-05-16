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
                path=project_root / "CLAUDE.md",
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

    surfaces[project_root / "CLAUDE.md"] = apply_managed_header(
        "# CLAUDE.md\n\n"
        "This repository uses AUDiaGentic workflow jobs.\n\n"
        "## Bridge\n\n"
        "When a prompt begins with a workflow tag, route it through the repo-owned bridge:\n\n"
        "```powershell\n"
        "python tools/claude_prompt_trigger_bridge.py --project-root .\n"
        "```\n\n"
        "If a hook surface is available, `UserPromptSubmit` should hand the raw prompt to the bridge\n"
        "before planning starts. If the hook surface is partial, fall back to the bridge.\n"
    )
    surfaces[project_root / ".claude" / "rules" / "prompt-tags.md"] = apply_managed_header(
        "# Prompt tag doctrine\n\n"
        "Rules:\n\n"
        "- parse only the first non-empty line for the workflow tag\n"
        "- keep tag semantics identical to the shared AUDiaGentic launch contract\n"
        "- do not invent provider-specific alternate tags\n"
        "- preserve raw prompt text in provenance metadata\n"
        "- route tagged prompts through the shared bridge when a native hook path is not stable\n"
    )
    return surfaces


register_renderer("claude", render)
register_contribution_renderer("claude", render_contributions)
