"""Component-driven action discovery — reads actions from installed component configs.

Each component config YAML can declare ``contributions`` entries pointing to
action feature descriptor files. Actions are owned by the component that declares them; the
providers component surfaces them on every installed provider.

Action feature descriptor files live under a component's config subdirectory and are
referenced by relative path from the config root. Each descriptor must have
``type: feature`` and ``kind: action``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.loader import load_feature_from_yaml
from audiagentic.paths import SRC_ROOT

from .base import ActionDescriptor, ActionFile, ActionInstruction, ActionPrompt
from .registry import register

_CONFIG_ROOT = SRC_ROOT / "audiagentic" / "config"


def _tag_loader_error(path: Path, code: str, message: str, **details: Any) -> AudiaGenticError:
    return AudiaGenticError(
        code=code,
        kind="providers",
        message=message,
        details={"path": str(path), **details},
    )


def _as_str_tuple(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, str) and item)


def _load_files(raw: Any) -> tuple[ActionFile, ...]:
    if not isinstance(raw, list):
        return ()
    files: list[ActionFile] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        rel_path = entry.get("path")
        lifecycle = entry.get("lifecycle")
        if not (isinstance(rel_path, str) and isinstance(lifecycle, str)):
            continue
        files.append(ActionFile(
            rel_path=rel_path,
            lifecycle=lifecycle,
            description=entry.get("description", ""),
        ))
    return tuple(files)


def _load_contributions(raw: Any) -> tuple[ActionInstruction, ...]:
    if not isinstance(raw, list):
        return ()
    contributions: list[ActionInstruction] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        contribution_id = entry.get("id")
        title = entry.get("title")
        content = entry.get("content") or {}
        body = content.get("body") if isinstance(content, dict) else None
        if not all(isinstance(v, str) and v for v in (contribution_id, title, body)):
            continue
        preferred = entry.get("preferred-targets") or []
        contributions.append(ActionInstruction(
            contribution_id=contribution_id,
            title=title,
            body=body,
            preferred_targets=_as_str_tuple(preferred),
        ))
    return tuple(contributions)


def _load_prompts(raw: Any) -> tuple[ActionPrompt, ...]:
    if not isinstance(raw, list):
        return ()
    prompts: list[ActionPrompt] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        content_file = entry.get("content-file")
        if not (isinstance(name, str) and isinstance(content_file, str)):
            continue
        prompts.append(ActionPrompt(name=name, content_file=content_file))
    return tuple(prompts)


def _load_primary_instruction(data: dict, path: Path) -> ActionInstruction | None:
    """Load the top-level primary instruction from an action YAML, if declared."""
    contribution_id = data.get("id")
    title = data.get("title")
    content = data.get("content") or {}
    body = content.get("body") if isinstance(content, dict) else None
    if not all(isinstance(v, str) and v for v in (contribution_id, title, body)):
        return None
    preferred = data.get("preferred-targets") or []
    return ActionInstruction(
        contribution_id=contribution_id,
        title=title,
        body=body,
        preferred_targets=_as_str_tuple(preferred),
    )


def _descriptor_from_data(
    data: dict[str, Any],
    path: Path,
    owner_component_id: str = "",
) -> ActionDescriptor:
    tag_id = data.get("tag-id")
    if not isinstance(tag_id, str) or not tag_id:
        raise _tag_loader_error(
            path,
            "VAL-PTAG-004",
            "missing or empty tag-id",
        )

    # Primary instruction declared at top level; additional via `instructions:` list.
    primary = _load_primary_instruction(data, path)
    additional = _load_contributions(data.get("instructions") or data.get("surface-contributions"))
    all_instructions = ((primary,) if primary else ()) + additional

    descriptor = ActionDescriptor(
        tag_id=tag_id,
        display_name=data.get("display-name", tag_id),
        description=data.get("description", ""),
        skill_content_file=data.get("skill-content-file", "skill.md"),
        config_dir=path.parent,
        aliases=_as_str_tuple(data.get("aliases")),
        directives=_as_str_tuple(data.get("directives")),
        files=_load_files(data.get("files")),
        instructions=all_instructions,
        prompts=_load_prompts(data.get("prompts")),
        requires_body=bool(data.get("requires-body", True)),
        is_generic_tag=bool(data.get("is-generic-tag", False)),
        is_review_tag=bool(data.get("is-review-tag", False)),
        owner_component_id=owner_component_id,
    )
    register(descriptor)
    return descriptor


def load_action_feature_from_yaml(path: Path, owner_component_id: str = "") -> ActionDescriptor:
    """Parse an action feature YAML and register the ActionDescriptor projection."""
    feature = load_feature_from_yaml(path)
    data = feature.raw
    if data.get("kind") != "action":
        raise _tag_loader_error(
            path,
            "VAL-PTAG-002",
            "expected action feature kind",
            expected="action",
            actual=data.get("kind"),
        )
    return _descriptor_from_data(data, path, owner_component_id)


def load_tag_from_yaml(path: Path, owner_component_id: str = "") -> ActionDescriptor:
    """Parse an action feature YAML and return a registered ActionDescriptor."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise _tag_loader_error(
            path,
            "VAL-PTAG-001",
            "expected action descriptor YAML mapping",
            actual=type(data).__name__,
        )
    if data.get("type") != "feature":
        raise _tag_loader_error(
            path,
            "VAL-PTAG-003",
            "expected action descriptor type",
            expected="feature",
            actual=data.get("type"),
        )
    if data.get("kind") != "action":
        raise _tag_loader_error(
            path,
            "VAL-PTAG-002",
            "expected action feature kind",
            expected="action",
            actual=data.get("kind"),
        )
    return load_action_feature_from_yaml(path, owner_component_id)


def _load_tags_from_component_config(
    config_file: Path, config_root: Path, owner_component_id: str = ""
) -> list[ActionDescriptor]:
    """Read a component's config YAML and load any action file references.

    Scans the ``contributions:`` list (or legacy ``actions:`` list) for entries
    that carry a ``config:`` key pointing to an action descriptor file.
    """
    data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    # Support unified `contributions:` key and legacy `actions:` key.
    raw_entries = data.get("contributions") or data.get("actions")
    if not isinstance(raw_entries, list):
        return []
    descriptors: list[ActionDescriptor] = []
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        tag_config_path = entry.get("config")
        if not isinstance(tag_config_path, str):
            continue
        tag_path = (config_root / tag_config_path).resolve()
        if not tag_path.exists():
            raise FileNotFoundError(
                f"action config declared in {config_file} not found: {tag_path}"
            )
        descriptors.append(load_action_feature_from_yaml(tag_path, owner_component_id))
    return descriptors


def load_all_tags(config_root: Path | None = None) -> list[ActionDescriptor]:
    """Load and register all actions declared via ``actions`` in component configs.

    Scans every registered ComponentDescriptor for a ``config_path``, reads its
    detailed config YAML, and loads any ``actions`` entries found there.

    Idempotent — re-registering an already-known tag-id overwrites silently.
    """
    from audiagentic.foundation.components.loader import register_all_components  # noqa: PLC0415
    from audiagentic.foundation.components.registry import all_descriptors  # noqa: PLC0415

    register_all_components()
    root = (config_root or _CONFIG_ROOT).resolve()
    descriptors: list[ActionDescriptor] = []
    for component in sorted(all_descriptors().values(), key=lambda d: d.component_id):
        if not component.yaml_path or not component.yaml_path.exists():
            continue
        descriptors.extend(
            _load_tags_from_component_config(component.yaml_path, root, component.component_id)
        )
    return descriptors
