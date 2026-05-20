"""Skill surface management — regenerate provider skill surface files from canonical tags.

Migrated from tools/misc/regenerate_tag_surfaces.py.

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
import os
import sys
import tempfile
from pathlib import Path

from audiagentic.components.optional.agent_jobs.prompt_syntax import load_prompt_syntax
from audiagentic.components.optional.providers.surfaces.base import SkillDefinition, apply_managed_blocks
from audiagentic.components.optional.providers.surfaces.manager import build_provider_surface_blocks
from audiagentic.components.optional.providers.surfaces.registry import load_renderer_registry


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


def _load_skill_definition(path: Path, tag: str) -> SkillDefinition:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"canonical skill file missing frontmatter: {path}")
    _, frontmatter, body = text.split("---", 2)
    meta = _parse_frontmatter(frontmatter)
    body_lines = [line.rstrip() for line in body.strip().splitlines()]
    title = next((line[2:].strip() for line in body_lines if line.startswith("# ")), f"{tag} skill")
    return SkillDefinition(
        tag=tag,
        name=meta.get("name", tag),
        description=meta.get("description", ""),
        title=title,
        trigger=_parse_section(body_lines, "Trigger"),
        do=_parse_section(body_lines, "Do"),
        dont=_parse_section(body_lines, "Do not"),
    )


def _load_canonical_skills(project_root: Path, syntax: dict[str, object]) -> list[SkillDefinition]:
    skills_root = project_root / ".audiagentic" / "skills"
    canonical_tags = syntax.get("canonical-tags")
    if not isinstance(canonical_tags, list):
        raise ValueError("prompt syntax missing canonical-tags list")
    skills: list[SkillDefinition] = []
    for tag in canonical_tags:
        if not isinstance(tag, str) or not tag:
            continue
        skill_path = skills_root / tag / "skill.md"
        if not skill_path.exists():
            raise FileNotFoundError(f"missing canonical skill source: {skill_path}")
        skills.append(_load_skill_definition(skill_path, tag))
    return skills


def _build_base_surfaces(project_root: Path, syntax: dict[str, object]) -> dict[Path, str]:
    """Build rendered surfaces from provider renderers (without contribution overlays)."""
    skills = _load_canonical_skills(project_root, syntax)
    surface_config = syntax.get("skill-surfaces")
    if not isinstance(surface_config, dict):
        raise ValueError("prompt syntax missing skill-surfaces config")
    renderers = load_renderer_registry()
    surfaces: dict[Path, str] = {}
    for provider, config in surface_config.items():
        if not isinstance(provider, str) or not isinstance(config, dict):
            continue
        renderer_name = config.get("renderer")
        if not isinstance(renderer_name, str):
            raise ValueError(f"skill surface for {provider} missing renderer")
        renderer = renderers.get(renderer_name)
        if renderer is None:
            raise ValueError(f"no renderer registered for {renderer_name}")
        rendered = renderer(project_root=project_root, syntax=syntax, skills=skills, config=config)
        overlaps = set(surfaces).intersection(rendered)
        if overlaps:
            raise ValueError(f"duplicate generated surface(s): {sorted(str(path) for path in overlaps)}")
        surfaces.update(rendered)
    return surfaces


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.stem + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


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
    """Regenerate skill surface files from canonical tags.

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
            _write_atomic(path, desired)

    if check:
        if diffs:
            print("Tag surface regeneration check failed:")
            for rel_path, diff_text in diffs:
                print(f"- {rel_path}")
                if diff_text:
                    print(diff_text)
            return 1
        print("Tag surface regeneration check passed.")
        return 0

    if dry_run:
        if diffs:
            print("Tag surface regeneration dry run:")
            for rel_path, diff_text in diffs:
                print(f"- {rel_path}")
                if diff_text:
                    print(diff_text)
        else:
            print("Tag surface regeneration dry run: no changes.")
        return 0

    if diffs:
        print("Tag surface regeneration wrote:")
        for rel_path, _ in diffs:
            print(f"- {rel_path}")
    else:
        print("Tag surface regeneration: no changes.")
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
