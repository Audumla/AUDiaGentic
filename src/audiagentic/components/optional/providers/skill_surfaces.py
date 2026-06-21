"""Skill surface management — regenerate provider skill surface files from the tag registry.

Public API
----------
build_skill_surfaces(project_root, syntax) -> dict[Path, str]
    Build final rendered surfaces including contribution overlays.

regenerate_skill_surfaces(project_root, *, dry_run, check) -> int
    Main entry point; returns exit code. Supports --check and --dry-run CLI modes.
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from audiagentic.cli_io import print_message
from audiagentic.components.optional.agent_jobs.prompt_syntax import load_prompt_syntax
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.components.optional.providers.surfaces.base import (
    SkillDefinition,
    apply_managed_blocks,
)
from audiagentic.components.optional.providers.surfaces.manager import build_provider_surface_blocks
from audiagentic.components.optional.providers.surfaces.registry import load_renderer_registry
from audiagentic.foundation.io import atomic_write_text


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="skill_surfaces")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def _parse_frontmatter(block: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def _parse_section(lines: list[str], section_name: str) -> list[str]:
    capture = False
    items: list[str] = []
    target = f"{section_name}:"
    for line in lines:
        stripped = line.strip()
        if stripped == target:
            capture = True
            continue
        if capture and stripped.endswith(":") and not stripped.startswith("-"):
            break
        if capture and stripped.startswith("- "):
            items.append(stripped[2:])
    return items


def _skill_definition_from_content(tag_id: str, content: str) -> SkillDefinition:
    """Parse a skill.md string (with YAML frontmatter) into a SkillDefinition."""
    if not content.startswith("---\n"):
        raise AudiaGenticError(
            code="VAL-PROV-SKILL-001",
            kind="providers",
            message=f"skill content for {tag_id!r} missing frontmatter",
            details={"tag_id": tag_id},
        )
    _, frontmatter, body = content.split("---", 2)
    meta = _parse_frontmatter(frontmatter)
    body_lines = [line.rstrip() for line in body.strip().splitlines()]
    title = next((line[2:].strip() for line in body_lines if line.startswith("# ")), f"{tag_id} skill")
    return SkillDefinition(
        tag=tag_id,
        name=meta.get("name", tag_id),
        description=meta.get("description", ""),
        title=title,
        trigger=_parse_section(body_lines, "Trigger"),
        do=_parse_section(body_lines, "Do"),
        dont=_parse_section(body_lines, "Do not"),
    )


def _load_skills_from_registry(project_root: Path | None = None) -> list[SkillDefinition]:
    """Load SkillDefinitions from the tag registry.

    If a project-local override exists at .audiagentic/skills/<tag>/skill.md it
    takes precedence over the tag package's bundled skill.md.
    """
    from audiagentic.components.optional.providers.surfaces.contributions import (  # noqa: PLC0415
        active_tag_ids,
    )
    from audiagentic.components.optional.providers.tags.registry import (  # noqa: PLC0415
        all_tags_loaded,
    )
    tags = all_tags_loaded()
    active = active_tag_ids(project_root)
    skills: list[SkillDefinition] = []
    for tag_id, descriptor in sorted(tags.items()):
        # Skip tags whose owning component is disabled/uninstalled so regeneration
        # cannot resurrect skill files that prune removed.
        if tag_id not in active:
            continue
        # Project-level override wins if present
        if project_root is not None:
            override = project_root / ".audiagentic" / "skills" / tag_id / "skill.md"
            if override.exists():
                content = override.read_text(encoding="utf-8")
                skills.append(_skill_definition_from_content(tag_id, content))
                continue
        skills.append(_skill_definition_from_content(tag_id, descriptor.skill_content()))
    return skills


def _build_base_surfaces(project_root: Path, syntax: dict[str, object]) -> dict[Path, str]:
    """Build rendered surfaces from provider renderers (without contribution overlays)."""
    skills = _load_skills_from_registry(project_root)
    surface_config = syntax.get("skill-surfaces")
    if not isinstance(surface_config, dict):
        raise AudiaGenticError(
            code="VAL-PROV-SKILL-002",
            kind="providers",
            message="prompt syntax missing skill-surfaces config",
        )
    renderers = load_renderer_registry()
    surfaces: dict[Path, str] = {}
    for provider, config in surface_config.items():
        if not isinstance(provider, str) or not isinstance(config, dict):
            continue
        renderer_name = config.get("renderer")
        if not isinstance(renderer_name, str):
            raise AudiaGenticError(
                code="VAL-PROV-SKILL-003",
                kind="providers",
                message=f"skill surface for {provider} missing renderer",
                details={"provider": provider},
            )
        renderer = renderers.get(renderer_name)
        if renderer is None:
            raise AudiaGenticError(
                code="VAL-PROV-SKILL-004",
                kind="providers",
                message=f"no renderer registered for {renderer_name}",
                details={"renderer_name": renderer_name},
            )
        rendered = renderer(project_root=project_root, syntax=syntax, skills=skills, config=config)
        overlaps = set(surfaces).intersection(rendered)
        if overlaps:
            raise AudiaGenticError(
                code="VAL-PROV-SKILL-005",
                kind="providers",
                message=f"duplicate generated surface(s): {sorted(str(path) for path in overlaps)}",
                details={"overlaps": [str(p) for p in overlaps]},
            )
        surfaces.update(rendered)
    return surfaces



def _apply_contributions(project_root: Path, surfaces: dict[Path, str]) -> dict[Path, str]:
    """Overlay contribution blocks onto the base render output for each path."""
    from collections import defaultdict

    blocks = build_provider_surface_blocks(project_root)
    grouped: dict[Path, list] = defaultdict(list)
    for block in blocks:
        if block.path in surfaces:
            grouped[block.path].append(block)
    result = dict(surfaces)
    for path, file_blocks in grouped.items():
        result[path] = apply_managed_blocks(result[path], file_blocks)
    return result


def _diff_text(path: Path, current: str, desired: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            current.splitlines(),
            desired.splitlines(),
            fromfile=f"a/{path.as_posix()}",
            tofile=f"b/{path.as_posix()}",
            lineterm="",
        )
    )


def build_skill_surfaces(project_root: Path, syntax: dict) -> dict[Path, str]:
    """Build final skill surfaces (render + contribution overlays).

    Parameters
    ----------
    project_root:
        Absolute path to the repository root.
    syntax:
        Parsed prompt-syntax config dict (as returned by load_prompt_syntax).

    Returns
    -------
    dict[Path, str]
        Mapping of absolute output path -> desired file content.
    """
    return _apply_contributions(project_root, _build_base_surfaces(project_root, syntax))


def regenerate_skill_surfaces(
    project_root: Path,
    *,
    dry_run: bool = False,
    check: bool = False,
) -> int:
    """Regenerate skill surface files from the tag registry.

    Parameters
    ----------
    project_root:
        Absolute path to the repository root.
    dry_run:
        If True, print diffs but do not write files.
    check:
        If True, return exit code 1 if any surfaces are out of date (CI mode).

    Returns
    -------
    int
        Exit code: 0 for success/no changes, 1 for check failures.
    """
    syntax = load_prompt_syntax(project_root)
    surfaces = build_skill_surfaces(project_root, syntax)
    diffs: list[tuple[Path, str]] = []

    for path, desired in sorted(surfaces.items(), key=lambda item: str(item[0])):
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == desired:
            continue
        diffs.append((path.relative_to(project_root), _diff_text(path.relative_to(project_root), current, desired)))
        if not check and not dry_run:
            atomic_write_text(path, desired)

    if check:
        if diffs:
            print_message("Tag surface regeneration check failed:")
            for rel_path, diff_text in diffs:
                print_message(f"- {rel_path}")
                if diff_text:
                    print_message(diff_text)
            return 1
        print_message("Tag surface regeneration check passed.")
        return 0

    if dry_run:
        if diffs:
            print_message("Tag surface regeneration dry run:")
            for rel_path, diff_text in diffs:
                print_message(f"- {rel_path}")
                if diff_text:
                    print_message(diff_text)
        else:
            print_message("Tag surface regeneration dry run: no changes.")
        return 0

    if diffs:
        print_message("Tag surface regeneration wrote:")
        for rel_path, _ in diffs:
            print_message(f"- {rel_path}")
    else:
        print_message("Tag surface regeneration: no changes.")
    return 0


def run(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_root = Path(args.project_root).resolve()
    return regenerate_skill_surfaces(
        project_root,
        dry_run=args.dry_run,
        check=args.check,
    )


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
