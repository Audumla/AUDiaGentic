"""Provider-owned loading for the shared prompt-syntax document.

The document describes provider-facing tags, aliases and rendered skill
surfaces.  Requester components may use the result through ``providers_api``;
they must not become a dependency of provider adapters or surface generation.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from audiagentic.components.providers.services.public_prompt_operations import (
    get_prompt_syntax_defaults,
)
from audiagentic.foundation.io import load_yaml_file

_DIRECTIVE_ALIASES: dict[str, str] = {
    "agent": "provider",
    "subject": "id",
    "ctx": "context",
    "out": "output",
    "t": "template",
}


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
        if key != "extends":
            merged[key] = deepcopy(value)
    return merged


def load_prompt_syntax(
    project_root: Path | None,
    profile_name: str | None = None,
) -> dict[str, Any]:
    """Load provider-owned defaults and an optional project syntax overlay."""
    syntax = get_prompt_syntax_defaults()
    syntax["directive-aliases"] = dict(_DIRECTIVE_ALIASES)
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
        selected = profile_name or payload.get("default-profile") or syntax.get("default-profile")
        if isinstance(selected, str) and selected:
            syntax = _merge_dict(syntax, _resolve_profile(profiles, selected))
    return syntax
