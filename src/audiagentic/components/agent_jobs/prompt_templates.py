"""Prompt template loading and rendering helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def _template_roots(project_root: Path, tag: str, provider_id: str) -> list[Path]:
    roots = [project_root / ".audiagentic" / "prompts" / tag]
    if tag.startswith("ag-"):
        roots.append(project_root / ".audiagentic" / "prompts" / tag.removeprefix("ag-"))
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(
            [
                root / f"{provider_id}.md",
                root / "shared.md",
                root / "default.md",
            ]
        )
    return candidates


def load_prompt_template(project_root: Path, *, tag: str, provider_id: str, template_name: str | None = None) -> tuple[str | None, Path | None]:
    candidates = []
    if template_name:
        roots = [project_root / ".audiagentic" / "prompts" / tag]
        if tag.startswith("ag-"):
            roots.append(project_root / ".audiagentic" / "prompts" / tag.removeprefix("ag-"))
        for root in roots:
            candidates.append(root / f"{template_name}.md")
            candidates.append(root / provider_id / f"{template_name}.md")
    candidates.extend(_template_roots(project_root, tag, provider_id))
    for path in candidates:
        if path.exists():
            return path.read_text(encoding="utf-8"), path
    packaged = _load_packaged_prompt_template(tag=tag, template_name=template_name)
    if packaged is not None:
        return packaged
    return None, None


def _load_packaged_prompt_template(*, tag: str, template_name: str | None) -> tuple[str, Path | None] | None:
    from audiagentic.components.providers.tags.registry import (
        all_tags,  # noqa: PLC0415
    )

    descriptor = all_tags().get(tag)
    if descriptor is None and tag.startswith("ag-"):
        descriptor = all_tags().get(tag.removeprefix("ag-"))
    if descriptor is None:
        return None

    requested = template_name or "default"
    for prompt in descriptor.prompts:
        if prompt.name != requested:
            continue
        source = descriptor.config_dir / prompt.content_file
        if source.exists():
            return source.read_text(encoding="utf-8"), source
        bodies = [
            instruction.body.strip()
            for instruction in descriptor.instructions
            if instruction.body.strip()
        ]
        content = "\n\n".join(bodies) or descriptor.description or f"{descriptor.display_name} prompt"
        return content.rstrip() + "\n", None
    return None


def load_prompt_context(project_root: Path, context_name: str | None) -> tuple[str | None, Path | None]:
    if not context_name:
        return None, None
    context_path = project_root / ".audiagentic" / "prompts" / "context" / f"{context_name}.md"
    if context_path.exists():
        return context_path.read_text(encoding="utf-8"), context_path
    return context_name, None


def render_prompt_template(template_text: str, values: dict[str, Any]) -> str:
    rendered = template_text
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", "" if value is None else str(value))
    return rendered.strip()
