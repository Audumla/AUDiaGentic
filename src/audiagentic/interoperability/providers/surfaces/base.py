from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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
    kind: str
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


def managed_block(block_id: str, content: str) -> str:
    body = content.strip()
    return (
        f"<!-- AUDIAGENTIC:BEGIN {block_id} -->\n"
        f"{body}\n"
        f"<!-- AUDIAGENTIC:END {block_id} -->"
    )


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
