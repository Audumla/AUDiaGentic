"""Prompt syntax profile loading and alias normalization."""
from __future__ import annotations

import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import load_yaml_file

logger = logging.getLogger(__name__)

# Base directive aliases that apply regardless of which tags are loaded.
_DIRECTIVE_ALIASES: dict[str, str] = {
    "agent": "provider",
    "subject": "id",
    "ctx": "context",
    "out": "output",
    "t": "template",
}

def _build_default_syntax() -> dict[str, Any]:
    """Build the default prompt syntax dict from the tag registry."""
    from audiagentic.components.providers.tags.registry import (  # noqa: PLC0415
        all_tags_loaded,
    )
    tags = all_tags_loaded()
    canonical_tags = sorted(tags)
    tag_aliases: dict[str, str] = {}
    for tag_id, descriptor in tags.items():
        tag_aliases[tag_id] = tag_id   # identity
        for alias in descriptor.aliases:
            tag_aliases[alias] = tag_id

    generic_tag = next(
        (tag_id for tag_id, d in tags.items() if d.is_generic_tag),
        None,
    )
    review_tag = next(
        (tag_id for tag_id, d in tags.items() if d.is_review_tag),
        None,
    )
    implement_tag = next(
        (tag_id for tag_id, d in tags.items() if not d.is_generic_tag and not d.is_review_tag and "implement" in tag_id),
        canonical_tags[0] if canonical_tags else "ag-implement",
    )
    no_body_required = [tag_id for tag_id, d in tags.items() if not d.requires_body]

    return {
        "contract-version": "v1",
        "default-profile": "shared",
        "generic-tag": generic_tag or "adhoc",
        "no-body-required-tags": no_body_required,
        "review-tag": review_tag or "ag-review",
        "implement-tag": implement_tag,
        "canonical-tags": canonical_tags,
        "tag-aliases": tag_aliases,
        "skill-surfaces": {},   # populated dynamically below
        "provider-aliases": {},
        "directive-aliases": dict(_DIRECTIVE_ALIASES),
    }


def _derive_skill_surfaces() -> dict[str, Any]:
    from audiagentic.components.providers.descriptors.registry import (  # noqa: PLC0415
        all_descriptors,
    )
    result: dict[str, Any] = {}
    for pid, descriptor in all_descriptors().items():
        if descriptor.skill_surface_path:
            result[pid] = {"renderer": pid, "path": descriptor.skill_surface_path}
    return result


def _derive_provider_aliases() -> dict[str, str]:
    from audiagentic.components.providers.descriptors.registry import (  # noqa: PLC0415
        provider_alias_map,
    )
    return provider_alias_map()


def load_no_body_required_tags(syntax: dict[str, Any]) -> set[str]:
    """Return the set of tags that do not require a prompt body."""
    tags = syntax.get("no-body-required-tags")
    if isinstance(tags, list):
        return {t for t in tags if isinstance(t, str) and t}
    from audiagentic.components.providers.tags.registry import (  # noqa: PLC0415
        no_body_required_tag_ids,
    )
    return no_body_required_tag_ids()


def load_review_tag(syntax: dict[str, Any]) -> str:
    """Return the canonical review tag name."""
    value = syntax.get("review-tag")
    if isinstance(value, str) and value.strip():
        return value.strip()
    from audiagentic.components.providers.tags.registry import (  # noqa: PLC0415
        review_tag_id,
    )
    return review_tag_id() or "ag-review"


def load_canonical_tags(syntax: dict[str, Any]) -> set[str]:
    """Return the set of canonical tag names from a loaded syntax dict."""
    tags = syntax.get("canonical-tags")
    if isinstance(tags, list):
        return {t for t in tags if isinstance(t, str) and t}
    from audiagentic.components.providers.tags.registry import (  # noqa: PLC0415
        canonical_tag_ids,
    )
    return set(canonical_tag_ids())


def _merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _merge_dict(deepcopy(base[key]), value)
        else:
            base[key] = deepcopy(value)
    return base


def _resolve_profile(profiles: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profile = profiles.get(profile_name, {})
    if not isinstance(profile, dict):
        return {}
    base_name = profile.get("extends")
    base_profile: dict[str, Any] = {}
    if isinstance(base_name, str) and base_name:
        base_profile = _resolve_profile(profiles, base_name)
    merged = deepcopy(base_profile)
    for key, value in profile.items():
        if key == "extends":
            continue
        merged[key] = deepcopy(value)
    return merged


def load_prompt_syntax(project_root: Path | None, profile_name: str | None = None) -> dict[str, Any]:
    syntax = _build_default_syntax()
    syntax["skill-surfaces"] = _derive_skill_surfaces()
    syntax["provider-aliases"] = _derive_provider_aliases()

    if project_root is None:
        return syntax

    syntax_path = project_root / ".audiagentic" / "config" / "execution" / "prompt-syntax.yaml"
    if not syntax_path.exists():
        return syntax

    payload = load_yaml_file(syntax_path)
    if not isinstance(payload, dict):
        return syntax

    shared_payload = {
        key: value
        for key, value in payload.items()
        if key not in {"contract-version", "default-profile", "profiles"}
    }
    syntax = _merge_dict(syntax, shared_payload)

    profiles = payload.get("profiles", {})
    if isinstance(profiles, dict):
        selected_profile = profile_name or payload.get("default-profile") or syntax.get("default-profile")
        if isinstance(selected_profile, str) and selected_profile:
            syntax = _merge_dict(syntax, _resolve_profile(profiles, selected_profile))

    return syntax
