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

    tag_examples = "\n".join(tag_alias_examples(syntax))
    provider_examples = "\n".join(provider_alias_examples(syntax))
    canonical_lines = "\n".join(f"- `@{tag}`" for tag in canonical_tags(syntax))
    surfaces[project_root / "AGENTS.md"] = apply_managed_header(
        "# AGENTS.md\n\n"
        "This repository uses canonical prompt tags to launch AUDiaGentic workflow jobs.\n\n"
        "## Canonical rule\n\n"
        f"- Do not reinterpret {', '.join(f'`@{tag}`' for tag in canonical_tags(syntax))}.\n"
        "- Route the raw tagged prompt through the repo-owned bridge instead of inventing a separate\n"
        "  workflow semantics layer.\n"
        "- Keep provenance visible: provider id, surface, and session id should survive normalization.\n"
        "- Canonical names are config-managed in `.audiagentic/prompt-syntax.yaml`; run\n"
        "  `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases.\n\n"
        "## Prompt-calling protocol\n\n"
        "If a prompt begins with a canonical tag, treat it as a workflow launch request, not ordinary\n"
        "chat.\n\n"
        "## Bridge mechanics\n\n"
        "The bridge is the execution boundary for tagged prompts.\n\n"
        "- Read the raw tagged prompt, including the first non-empty line and the prompt body.\n"
        "- Normalize the tag, provider shorthand, and argument aliases using\n"
        "  `.audiagentic/prompt-syntax.yaml`.\n"
        "- Preserve provenance fields through normalization: provider id, surface, and session id.\n"
        "- Apply project defaults when the prompt omits `id`, `context`, `output`, or `template`.\n"
        "- Treat the canonical action tags as workflow selectors, not as free-form instructions:\n"
        f"{canonical_lines}\n"
        "- Treat provider shorthands as provider selectors that still route through the same normalized\n"
        "  launch contract.\n"
        "- If the prompt is tagged but no explicit subject is supplied, let the bridge create the default\n"
        "  generic subject/job identity rather than inventing ad hoc semantics.\n"
        "- Stream or capture provider output through AUDiaGentic-owned runtime artifacts; the provider\n"
        "  should not own persistence policy.\n\n"
        "The Codex launch path is:\n\n"
        "```powershell\n"
        "python tools/codex_prompt_trigger_bridge.py --project-root .\n"
        "```\n\n"
        "The shared bridge normalizes the raw prompt and forwards it into `prompt-launch`, so the\n"
        "tagged prompt becomes a job request with preserved provenance and project defaults.\n\n"
        "## Codex path\n\n"
        "Codex should use the shared prompt-trigger bridge:\n\n"
        "```powershell\n"
        "python tools/codex_prompt_trigger_bridge.py --project-root .\n"
        "```\n\n"
        "If a hook or instruction surface is partial, fall back to the bridge and keep the shared launch\n"
        "grammar unchanged.\n\n"
        "## Standard prompt shape\n\n"
        "Prefer the short, defaults-first form:\n\n"
        "```text\n"
        "@ag-review provider=codex id=job_001 ctx=documentation t=review-default\n"
        "Review the current project state and call out any gaps.\n"
        "```\n\n"
        "When a provider/tag default template exists under `.audiagentic/prompts/<tag>/`, the shortest\n"
        "form is also valid:\n\n"
        "```text\n"
        "@ag-review\n"
        "```\n\n"
        "In that case the bridge should:\n"
        "- resolve the provider from the suffix\n"
        "- load the provider or shared default template\n"
        "- create the default job/subject identity if none is supplied\n"
        "- preserve provenance through normalization\n\n"
        "The bridge should accept the long-form canonical names as well:\n\n"
        "- `provider`\n"
        "- `id`\n"
        "- `context`\n"
        "- `output`\n"
        "- `template`\n\n"
        "and the common aliases:\n\n"
        "- `ctx` -> `context`\n"
        "- `out` -> `output`\n"
        "- `t` -> `template`\n\n"
        "## Tag and provider aliases\n\n"
        "Centralized in `.audiagentic/prompt-syntax.yaml`. Available shortcuts:\n\n"
        f"{tag_examples}\n"
        f"{provider_examples}\n\n"
        "## Skills\n\n"
        + "\n".join(f"- `{skill.tag}`" for skill in skills)
        + "\n\n"
        "## Review doctrine\n\n"
        "- review prompts should stay read-focused unless the normalized request explicitly allows more\n"
        "- do not broaden review into implementation work\n"
        "- keep tracked docs and release artifacts synchronized with the job record\n"
    )
    return surfaces
