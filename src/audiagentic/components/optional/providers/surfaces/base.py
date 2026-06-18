from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

_TEMPLATES_DIR = Path(__file__).parent / "templates"

MANAGED_MARKDOWN_HEADER = "<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->"

# A single managed region per file holds every AUDiaGentic-generated block. The
# boundary is one invisible comment pair (robust to re-render); the blocks inside
# use plain markdown headings for readability. The region is regenerated wholesale
# on each apply, so removing a contribution simply drops its block, and removing
# all contributions removes the region.
MANAGED_REGION_BEGIN = "<!-- ag:managed:begin -->"
MANAGED_REGION_END = "<!-- ag:managed:end -->"
MANAGED_REGION_NOTICE = (
    "_Managed by AUDiaGentic — generated from component configs. "
    "Edit the owning component and re-run surface apply; edits here are overwritten._"
)

_REGION_RE = re.compile(
    r"\n*" + re.escape(MANAGED_REGION_BEGIN) + r".*?" + re.escape(MANAGED_REGION_END) + r"\n*",
    re.DOTALL,
)
# Legacy per-block fences (pre-region format) — stripped on next apply so old
# files migrate to the single-region layout automatically.
_LEGACY_BLOCK_RE = re.compile(
    r"\n*<!-- AUDIAGENTIC:BEGIN (?P<id>[^>]+) -->.*?<!-- AUDIAGENTIC:END (?P=id) -->\n*",
    re.DOTALL,
)


@dataclass(frozen=True)
class SkillDefinition:
    tag: str
    name: str
    description: str
    title: str
    trigger: list[str]
    do: list[str]
    dont: list[str]


@dataclass(frozen=True)
class SurfaceContribution:
    contribution_id: str
    owner_component: str
    title: str
    body: str
    preferred_targets: tuple[str, ...] = ()


@dataclass(frozen=True)
class SurfaceBlock:
    path: Path
    block_id: str
    content: str


class ProviderSurfaceRenderer(Protocol):
    def render(
        self,
        *,
        project_root: Path,
        syntax: dict[str, Any],
        skills: list[SkillDefinition],
        config: dict[str, Any],
    ) -> dict[Path, str]:
        ...


class ProviderContributionRenderer(Protocol):
    def __call__(
        self,
        *,
        project_root: Path,
        contributions: list[SurfaceContribution],
    ) -> list[SurfaceBlock]:
        ...


def apply_managed_header(text: str) -> str:
    body = text.lstrip()
    if body.startswith(MANAGED_MARKDOWN_HEADER):
        return text
    return f"{MANAGED_MARKDOWN_HEADER}\n\n{text}"


def _load_template(adapter_dir: Path, filename: str, default_name: str) -> str:
    custom = adapter_dir / filename
    if custom.exists():
        return custom.read_text(encoding="utf-8")
    return (_TEMPLATES_DIR / default_name).read_text(encoding="utf-8")


def render_instruction_file(
    *,
    provider_id: str,
    instruction_file: str,
    adapter_dir: Path,
) -> str:
    """Render a provider's managed instruction file from its template."""
    return f"{MANAGED_MARKDOWN_HEADER}\n"


def render_rules_file(*, adapter_dir: Path, filename: str = "prompt-tags.md") -> str:
    """Render a provider's managed rules file from its template."""
    template_text = _load_template(adapter_dir, filename, "default_prompt_tags.md")
    return apply_managed_header(template_text)


def strip_managed_content(existing: str) -> str:
    """Remove the managed region and any legacy per-block fences, leaving user text."""
    text = _REGION_RE.sub("\n\n", existing)
    text = _LEGACY_BLOCK_RE.sub("\n\n", text)
    return text


def render_managed_region(blocks: list[SurfaceBlock]) -> str:
    """Render all blocks for a file into one fenced, regenerated managed region."""
    ordered = sorted(blocks, key=lambda b: b.block_id)
    parts = [block.content.strip() for block in ordered if block.content.strip()]
    body = "\n\n".join([MANAGED_REGION_NOTICE, *parts])
    return f"{MANAGED_REGION_BEGIN}\n{body}\n{MANAGED_REGION_END}"


def apply_managed_blocks(existing: str, blocks: list[SurfaceBlock]) -> str:
    """Replace the file's managed region with one regenerated from `blocks`.

    Strips any prior region and legacy per-block fences first (migration), then
    appends the freshly rendered region. An empty `blocks` removes the region
    entirely, leaving only user-authored content.
    """
    text = strip_managed_content(existing).rstrip()
    if not blocks:
        return f"{text}\n" if text else ""
    region = render_managed_region(blocks)
    combined = f"{text}\n\n{region}" if text else region
    return combined.rstrip() + "\n"


def canonical_tags(syntax: dict[str, Any]) -> list[str]:
    tags = syntax.get("canonical-tags")
    if isinstance(tags, list):
        return [tag for tag in tags if isinstance(tag, str) and tag]
    return []


def tag_alias_examples(syntax: dict[str, Any]) -> list[str]:
    aliases = syntax.get("tag-aliases")
    if not isinstance(aliases, dict):
        return []
    preferred_order = ["agp", "agi", "agr", "aga", "agc"]
    return [f"- `{alias}` -> `{aliases[alias]}`" for alias in preferred_order if isinstance(aliases.get(alias), str)]


def provider_alias_examples(syntax: dict[str, Any]) -> list[str]:
    aliases = syntax.get("provider-aliases")
    if not isinstance(aliases, dict):
        return []
    preferred_order = ["cx", "cld", "cln", "gm", "opc", "cp"]
    return [f"- `{alias}` -> `{aliases[alias]}`" for alias in preferred_order if isinstance(aliases.get(alias), str)]


def render_frontmatter_skill(skill: SkillDefinition, *, root_label: str) -> str:
    trigger_lines = "\n".join(f"- {item}" for item in skill.trigger)
    do_lines = "\n".join(f"- {item}" for item in skill.do)
    dont_lines = "\n".join(f"- {item}" for item in skill.dont)
    return (
        "---\n"
        f"name: {skill.name}\n"
        f"description: {skill.description}\n"
        "---\n\n"
        f"{MANAGED_MARKDOWN_HEADER}\n\n"
        f"# {skill.title}\n\n"
        f"Use this skill for canonical `@{skill.tag}` launches.\n\n"
        "Trigger:\n"
        f"{trigger_lines}\n\n"
        "Do:\n"
        f"{do_lines}\n\n"
        "Do not:\n"
        f"{dont_lines}\n\n"
        f"Root surface: `{root_label}`\n"
    )


def render_flat_skill(skill: SkillDefinition, *, provider_name: str, launch_example: str) -> str:
    trigger_lines = "\n".join(f"- {item}" for item in skill.trigger)
    do_lines = "\n".join(f"- {item}" for item in skill.do)
    dont_lines = "\n".join(f"- {item}" for item in skill.dont)
    return (
        f"{MANAGED_MARKDOWN_HEADER}\n\n"
        f"# {skill.title}\n\n"
        f"Provider surface: `{provider_name}`\n\n"
        f"Launch example: `{launch_example}`\n\n"
        f"Use this skill for canonical `@{skill.tag}` launches.\n\n"
        "Trigger:\n"
        f"{trigger_lines}\n\n"
        "Do:\n"
        f"{do_lines}\n\n"
        "Do not:\n"
        f"{dont_lines}\n"
    )


def resolve_tag_path(project_root: Path, template: str, tag: str) -> Path:
    return project_root / template.format(tag=tag)


def make_single_file_contribution_renderer(
    filename: str, *, heading: str = "##"
) -> ProviderContributionRenderer:
    """Factory for providers that write contributions to a single markdown file.

    Collapses ~9 near-identical render_contributions implementations into one
    factory call per provider, differing only by target filename.
    """
    def render_contributions(
        *, project_root: Path, contributions: list[SurfaceContribution]
    ) -> list[SurfaceBlock]:
        return [
            SurfaceBlock(
                path=project_root / filename,
                block_id=c.contribution_id,
                content=f"{heading} {c.title}\n\n{c.body.strip()}",
            )
            for c in contributions
        ]
    return render_contributions
