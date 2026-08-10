from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class ContributionKind(str, Enum):
    """Type of surface contribution."""
    RULE = "rule"
    CONTENT = "content"
    CONFIG_REFERENCE = "config-reference"


@dataclass(frozen=True)
class ContributionDescriptor:
    """Typed schema for a contribution entry in component YAML.

    Validates the raw YAML contribution before it becomes a SurfaceContribution.
    """
    id: str
    owner: str
    kind: ContributionKind = ContributionKind.CONTENT
    title: str = ""
    preferred_targets: tuple[str, ...] = ()
    content: dict[str, Any] | str | None = None
    config_reference: str | None = None
    skill_content_file: str | None = None


# Target kinds describe how content should surface.
KNOWN_TARGET_KINDS = frozenset({"skill", "instruction", "rule"})
KNOWN_PREFERRED_TARGETS = KNOWN_TARGET_KINDS


def validate_config_reference(config_path: str, component_id: str) -> str | None:
    """Validate that a config reference resolves to an existing file.

    Returns None if valid, or a warning message if the file does not exist.
    Config references are resolved relative to the package config directory.
    """
    from audiagentic.foundation.components.loader import (
        _COMPONENTS_CONFIG_DIR,
    )

    # Config references are relative to the package config dir (parent of components/)
    config_base = _COMPONENTS_CONFIG_DIR.parent
    candidate = config_base / config_path
    if not candidate.exists():
        return (
            f"Component {component_id!r}: config reference {config_path!r} "
            f"does not exist (resolved to {candidate})"
        )
    return None


def parse_contribution_descriptor(raw: dict[str, Any], default_owner: str) -> ContributionDescriptor | None:
    """Parse and validate a raw contribution dict into a typed descriptor.

    Returns None if the entry is invalid or should be skipped (e.g. config references).
    Raises AudiaGenticError for validation failures.
    """
    from audiagentic.foundation.contracts.errors import make_error  # noqa: PLC0415

    # Config references are handled by the tag loader, not surface contributions.
    if "config" in raw and "id" not in raw:
        return None

    contribution_id = raw.get("id")
    if not isinstance(contribution_id, str) or not contribution_id:
        raise make_error(
            prefix="VAL",
            component="SURF",
            number=1,
            kind="surface-contributions",
            message="Contribution missing required 'id' field",
            details={"raw": raw},
        )

    owner = raw.get("owner") if isinstance(raw.get("owner"), str) else default_owner
    if not owner:
        raise make_error(
            prefix="VAL",
            component="SURF",
            number=2,
            kind="surface-contributions",
            message=f"Contribution {contribution_id!r}: missing required 'owner' field",
            details={"contribution_id": contribution_id},
        )

    # Parse kind
    kind_raw = raw.get("kind", "content")
    try:
        kind = ContributionKind(kind_raw) if isinstance(kind_raw, str) else ContributionKind.CONTENT
    except ValueError:
        raise make_error(
            prefix="VAL",
            component="SURF",
            number=3,
            kind="surface-contributions",
            message=f"Contribution {contribution_id!r}: unknown kind {kind_raw!r}",
            details={
                "contribution_id": contribution_id,
                "kind": kind_raw,
                "allowed": list(ContributionKind.__members__),
            },
        )

    # Parse title
    title = raw.get("title") or raw.get("summary")
    if not isinstance(title, str) or not title:
        raise make_error(
            prefix="VAL",
            component="SURF",
            number=4,
            kind="surface-contributions",
            message=f"Contribution {contribution_id!r}: missing required 'title' field",
            details={"contribution_id": contribution_id},
        )

    # Parse preferred_targets
    preferred_targets = ()
    if "preferred-targets" in raw:
        raw_targets = raw["preferred-targets"]
        if isinstance(raw_targets, list):
            for target in raw_targets:
                if isinstance(target, str) and target:
                    if target not in KNOWN_PREFERRED_TARGETS:
                        logger.warning(
                            "Contribution %r: unknown preferred-target %r (known: %s)",
                            contribution_id,
                            target,
                            ", ".join(sorted(KNOWN_PREFERRED_TARGETS)),
                        )
                    preferred_targets += (target,)

    # Parse content
    content = raw.get("content")
    config_reference = raw.get("config")
    skill_content_file = raw.get("skill-content-file")

    return ContributionDescriptor(
        id=contribution_id,
        owner=owner,
        kind=kind,
        title=title,
        preferred_targets=preferred_targets,
        content=content,
        config_reference=config_reference,
        skill_content_file=skill_content_file,
    )


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
    def __call__(
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
    display_name: str | None = None,
) -> str:
    """Render a provider's managed instruction file from its template."""
    template_text = _load_template(adapter_dir, "instruction.md", "default_instruction.md")
    if display_name is None:
        from audiagentic.components.providers.descriptors.registry import (
            all_descriptors,  # noqa: PLC0415
        )

        descriptor = all_descriptors().get(provider_id)
        display_name = descriptor.display_name if descriptor is not None else provider_id
    rendered = template_text.replace("$display_name", display_name).rstrip() + "\n"
    return apply_managed_header(rendered)


def is_component_active(project_root: Path, component_id: str) -> bool:
    """Return True when a component is both installed and enabled."""
    from audiagentic.foundation.components.registry import is_enabled, is_installed  # noqa: PLC0415

    return is_installed(component_id, project_root) and is_enabled(component_id, project_root)


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


def make_standard_surface_renderer(
    provider_id: str,
    *,
    style: str = "flat-skill",
    instruction_file: str | None = None,
    adapter_dir: Path | None = None,
    launch_example_template: str = "@{tag}-{provider_id}",
) -> ProviderSurfaceRenderer:
    """Factory for descriptor-driven surface renderers (AR03).

    ``flat-skill`` reproduces the renderer previously copy-pasted per adapter:
    one flat skill file per tag (path template from config) plus the managed
    instruction file when agent-jobs is active. ``none`` renders no skill
    surfaces (for providers whose contributions target a shared file only).
    """
    def render(
        *,
        project_root: Path,
        syntax: dict[str, Any],
        skills: list[SkillDefinition],
        config: dict[str, Any],
    ) -> dict[Path, str]:
        del syntax
        surfaces: dict[Path, str] = {}
        if style == "none":
            return surfaces
        path_template = str(config["path"])
        for skill in skills:
            path = resolve_tag_path(project_root, path_template, skill.tag)
            surfaces[path] = apply_managed_header(
                render_flat_skill(
                    skill,
                    provider_name=provider_id,
                    launch_example=launch_example_template.format(
                        tag=skill.tag, provider_id=provider_id
                    ),
                )
            )

        if instruction_file and adapter_dir is not None and is_component_active(project_root, "agent-jobs"):
            surfaces[project_root / instruction_file] = render_instruction_file(
                provider_id=provider_id,
                instruction_file=instruction_file,
                adapter_dir=adapter_dir,
            )
        return surfaces

    return render


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
