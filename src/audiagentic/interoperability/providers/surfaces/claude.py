from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import (
    SkillDefinition,
    apply_managed_header,
    canonical_tags,
    provider_alias_examples,
    render_frontmatter_skill,
    resolve_tag_path,
    tag_alias_examples,
)


def render(
    *,
    project_root: Path,
    syntax: dict[str, Any],
    skills: list[SkillDefinition],
    config: dict[str, Any],
) -> dict[Path, str]:
    surfaces: dict[Path, str] = {}
    path_template = str(config["path"])

    for skill in skills:
        path = resolve_tag_path(project_root, path_template, skill.tag)
        surfaces[path] = apply_managed_header(
            render_frontmatter_skill(skill, root_label=path_template.format(tag=skill.tag))
        )

    canonical_lines = "\n".join(f"- {tag}" for tag in canonical_tags(syntax))
    tag_examples = "\n".join(tag_alias_examples(syntax))
    provider_examples = "\n".join(provider_alias_examples(syntax))
    surfaces[project_root / "CLAUDE.md"] = apply_managed_header(
        "# CLAUDE.md\n\n"
        "This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.\n\n"
        "## Canonical rule\n\n"
        f"- Do not reinterpret {', '.join(f'`@{tag}`' for tag in canonical_tags(syntax))}.\n"
        "- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate\n"
        "  workflow semantics layer.\n"
        "- Keep provenance visible: provider id, surface, and session id should survive normalization.\n\n"
        "## Bridge\n\n"
        "When a Claude prompt begins with a canonical tag, use the shared prompt-trigger bridge:\n\n"
        "```powershell\n"
        "python tools/claude_prompt_trigger_bridge.py --project-root .\n"
        "```\n\n"
        "If a hook surface is available, `UserPromptSubmit` should hand the raw prompt to the bridge\n"
        "before planning starts. If the hook surface is partial, fall back to the bridge and keep the\n"
        "shared launch grammar unchanged.\n\n"
        "## Tag shortcuts and aliases\n\n"
        "Tag and provider aliases are centralized in `.audiagentic/prompt-syntax.yaml` and work in all surfaces:\n\n"
        "Canonical tags:\n\n"
        f"{canonical_lines}\n\n"
        f"{tag_examples}\n\n"
        f"{provider_examples}\n\n"
        "All of these are equivalent:\n\n"
        "```text\n"
        "@ag-review provider=cline\n"
        "@agr provider=cline\n"
        "@review provider=cline\n"
        "@r provider=cline\n"
        "@ag-review-cline\n"
        "@r-cline\n"
        "```\n\n"
        "## Review doctrine\n\n"
        "- review prompts should stay read-focused unless the normalized request explicitly allows more\n"
        "- do not broaden review into implementation work\n"
        "- keep tracked docs and release artifacts synchronized with the job record\n"
    )
    surfaces[project_root / ".claude" / "rules" / "prompt-tags.md"] = apply_managed_header(
        "# Prompt tag doctrine\n\n"
        "Canonical tags:\n\n"
        + "\n".join(f"- `@{tag}`" for tag in canonical_tags(syntax))
        + "\n\nRules:\n\n"
        "- parse only the first non-empty line for the canonical tag\n"
        "- keep tag semantics identical to the shared AUDiaGentic launch contract\n"
        "- do not invent provider-specific alternate tags\n"
        "- preserve raw prompt text in provenance metadata\n"
        "- route tagged prompts through the shared bridge when a native hook path is not stable\n"
    )
    return surfaces
