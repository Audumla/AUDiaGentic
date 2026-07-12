"""Prompt template loading and rendering helpers."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.path_safety import ensure_contained
from audiagentic.foundation.templates import render_template as _render_dotted

logger = logging.getLogger(__name__)


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


def load_prompt_from_file(
    project_root: Path,
    template_path: str,
    source_label: str = "",
) -> tuple[str, Path]:
    """Load a prompt template from an explicit file path with containment safety.

    Parameters
    ----------
    project_root:
        Root of the AUDiaGentic project.
    template_path:
        File path from configuration (may be relative to ``project_root`` or
        absolute).
    source_label:
        Human-readable label for error context (e.g. trigger id, job name).

    Returns
    -------
    tuple[str, Path]
        The file contents and the resolved Path.

    Raises
    ------
    AudiaGenticError
        IO-PATH-001 if path escapes project root, IO-PTMPL-001 if file is
        missing, IO-PTMPL-002 on read errors.
    """
    source_prefix = f"{source_label}: " if source_label else ""

    try:
        resolved = ensure_contained(project_root, template_path)
    except AudiaGenticError as exc:
        if exc.code == "IO-PATH-001":
            raise AudiaGenticError(
                code="IO-PATH-001",
                kind="foundation",
                message=(
                    f"{source_prefix}prompt-template-file {template_path!r} "
                    f"resolves outside the project root."
                ),
                details={
                    "requested_path": template_path,
                    "project_root": str(project_root),
                },
            ) from exc
        raise

    if not resolved.is_file():
        raise AudiaGenticError(
            code="IO-PTMPL-001",
            kind="agent-jobs",
            message=(
                f"{source_prefix}prompt template file not found at {resolved}"
            ),
            details={
                "template_path": template_path,
                "resolved_path": str(resolved),
            },
        )

    try:
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise AudiaGenticError(
            code="IO-PTMPL-002",
            kind="agent-jobs",
            message=(
                f"{source_prefix}failed to read prompt template file {resolved}"
            ),
            details={
                "template_path": template_path,
                "error": str(exc),
            },
        ) from exc

    return content, resolved


def load_prompt_context(project_root: Path, context_name: str | None) -> tuple[str | None, Path | None]:
    if not context_name:
        return None, None
    context_path = project_root / ".audiagentic" / "prompts" / "context" / f"{context_name}.md"
    if context_path.exists():
        return context_path.read_text(encoding="utf-8"), context_path
    return context_name, None


def render_prompt_template(template_text: str, values: dict[str, Any]) -> str:
    """Render a prompt template with dotted-path placeholder support.

    Delegates to :func:`audiagentic.foundation.templates.render_template` for
    uniform dotted-path rendering. Flat keys (e.g. ``{id}``) and hyphenated keys
    (e.g. ``{project-root}``) continue to work as before. Additionally supports
    nested paths like ``{event.payload.id}``.
    """
    return _render_dotted(template_text, values).strip()
