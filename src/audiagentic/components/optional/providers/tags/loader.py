"""Component-driven tag discovery — reads agent-tags from installed component configs.

Each component config YAML can declare an ``agent-tags`` list of paths pointing to
tag descriptor files. Tags are owned by the component that declares them; the
providers component surfaces them on every installed provider.

Tag descriptor files (``descriptor.yaml`` + ``skill.md``) live under
``config/components/optional/agent-actions/tags/<name>/`` and are referenced by relative path from
the config root. Each descriptor must have ``type: agent-action``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from audiagentic.paths import SRC_ROOT

from .base import TagDescriptor, TagFile, TagPrompt, TagSurfaceContribution
from .registry import register

_CONFIG_ROOT = SRC_ROOT / "audiagentic" / "config"


def _as_str_tuple(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


def _load_files(raw: Any) -> tuple[TagFile, ...]:
    if not isinstance(raw, list):
        return ()
    files: list[TagFile] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        rel_path = entry.get("path")
        lifecycle = entry.get("lifecycle")
        if not (isinstance(rel_path, str) and isinstance(lifecycle, str)):
            continue
        files.append(TagFile(
            rel_path=rel_path,
            lifecycle=lifecycle,
            description=entry.get("description", ""),
        ))
    return tuple(files)


def _load_contributions(raw: Any) -> tuple[TagSurfaceContribution, ...]:
    if not isinstance(raw, list):
        return ()
    contributions: list[TagSurfaceContribution] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        contribution_id = entry.get("id")
        kind = entry.get("kind")
        title = entry.get("title")
        content = entry.get("content") or {}
        body = content.get("body") if isinstance(content, dict) else None
        if not all(isinstance(v, str) and v for v in (contribution_id, kind, title, body)):
            continue
        preferred = entry.get("preferred-targets") or []
        contributions.append(TagSurfaceContribution(
            contribution_id=contribution_id,
            kind=kind,
            title=title,
            body=body,
            preferred_targets=_as_str_tuple(preferred),
        ))
    return tuple(contributions)


def _load_prompts(raw: Any) -> tuple[TagPrompt, ...]:
    if not isinstance(raw, list):
        return ()
    prompts: list[TagPrompt] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        content_file = entry.get("content-file")
        if not (isinstance(name, str) and isinstance(content_file, str)):
            continue
        prompts.append(TagPrompt(name=name, content_file=content_file))
    return tuple(prompts)


def load_tag_from_yaml(path: Path) -> TagDescriptor:
    """Parse a single tag descriptor.yaml and return a registered TagDescriptor."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    if data.get("type") != "agent-action":
        raise ValueError(f"{path}: expected type=agent-action, got {data.get('type')!r}")
    tag_id = data.get("tag-id")
    if not isinstance(tag_id, str) or not tag_id:
        raise ValueError(f"{path}: missing or empty tag-id")
    descriptor = TagDescriptor(
        tag_id=tag_id,
        display_name=data.get("display-name", tag_id),
        description=data.get("description", ""),
        skill_content_file=data.get("skill-content-file", "skill.md"),
        config_dir=path.parent,
        aliases=_as_str_tuple(data.get("aliases")),
        directives=_as_str_tuple(data.get("directives")),
        files=_load_files(data.get("files")),
        surface_contributions=_load_contributions(data.get("surface-contributions")),
        prompts=_load_prompts(data.get("prompts")),
        requires_body=bool(data.get("requires-body", True)),
        is_generic_tag=bool(data.get("is-generic-tag", False)),
        is_review_tag=bool(data.get("is-review-tag", False)),
    )
    register(descriptor)
    return descriptor


def _load_tags_from_component_config(config_file: Path, config_root: Path) -> list[TagDescriptor]:
    """Read a component's detailed config YAML and load any declared agent-tags."""
    data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    raw_tags = data.get("agent-tags")
    if not isinstance(raw_tags, list):
        return []
    descriptors: list[TagDescriptor] = []
    for entry in raw_tags:
        if not isinstance(entry, dict):
            continue
        tag_config_path = entry.get("config")
        if not isinstance(tag_config_path, str):
            continue
        tag_path = (config_root / tag_config_path).resolve()
        if not tag_path.exists():
            raise FileNotFoundError(
                f"agent-tag config declared in {config_file} not found: {tag_path}"
            )
        descriptors.append(load_tag_from_yaml(tag_path))
    return descriptors


def load_all_tags(config_root: Path | None = None) -> list[TagDescriptor]:
    """Load and register all tags declared via ``agent-tags`` in component configs.

    Scans every registered ComponentDescriptor for a ``config_path``, reads its
    detailed config YAML, and loads any ``agent-tags`` entries found there.

    Idempotent — re-registering an already-known tag-id overwrites silently.
    """
    from audiagentic.foundation.components.loader import register_all_components  # noqa: PLC0415
    from audiagentic.foundation.components.registry import all_descriptors  # noqa: PLC0415

    register_all_components()
    root = (config_root or _CONFIG_ROOT).resolve()
    descriptors: list[TagDescriptor] = []
    for component in sorted(all_descriptors().values(), key=lambda d: d.component_id):
        if not component.yaml_path or not component.yaml_path.exists():
            continue
        descriptors.extend(_load_tags_from_component_config(component.yaml_path, root))
    return descriptors
