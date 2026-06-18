from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Protocol

_TEMPLATES_DIR = Path(__file__).parent / "templates"

MANAGED_MARKDOWN_HEADER = "<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->"


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
    template_text = _load_template(adapter_dir, "instruction.md", "default_instruction.md")
    content = Template(template_text).safe_substitute(
        display_name=instruction_file,
        provider_id=provider_id,
    )
    return apply_managed_header(content)


def render_rules_file(*, adapter_dir: Path, filename: str = "prompt-tags.md") -> str:
    """Render a provider's managed rules file from its template."""
    template_text = _load_template(adapter_dir, filename, "default_prompt_tags.md")
    return apply_managed_header(template_text)


def managed_block(block_id: str, content: str) -> str:
    body = content.strip()
    return (
        f"<!-- AUDIAGENTIC:BEGIN {block_id} -->\n"
        f"{body}\n"
        f"<!-- AUDIAGENTIC:END {block_id} -->"
    )


def prune_managed_blocks(existing: str, active_ids: set[str]) -> str:
    """Remove fenced blocks whose block_id is not in active_ids.

    Leaves all other content untouched. Returns the pruned text.
    """
    import re
    pattern = re.compile(
        r"\n*<!-- AUDIAGENTIC:BEGIN (?P<id>[^>]+) -->.*?<!-- AUDIAGENTIC:END (?P=id) -->\n*",
        re.DOTALL,
    )

    def _replace(match: re.Match) -> str:
        return "" if match.group("id") not in active_ids else match.group(0)

    pruned = pattern.sub(_replace, existing)
    return pruned.rstrip() + "\n" if pruned.strip() else ""


def apply_managed_blocks(existing: str, blocks: list[SurfaceBlock]) -> str:
    text = existing.rstrip()
    for block in blocks:
        rendered = managed_block(block.block_id, block.content)
        begin = f"<!-- AUDIAGENTIC:BEGIN {block.block_id} -->"
        end = f"<!-- AUDIAGENTIC:END {block.block_id} -->"
        start = text.find(begin)
        if start == -1:
            text = f"{text}\n\n{rendered}" if text else rendered
            continue
        finish = text.find(end, start)
        if finish == -1:
            text = f"{text}\n\n{rendered}" if text else rendered
            continue
        finish += len(end)
        text = f"{text[:start].rstrip()}\n\n{rendered}\n\n{text[finish:].lstrip()}".strip()
    return text.rstrip() + "\n"


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
