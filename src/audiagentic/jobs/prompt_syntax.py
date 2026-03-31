"""Prompt syntax profile loading and alias normalization."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PROMPT_SYNTAX: dict[str, Any] = {
    "contract-version": "v1",
    "default-profile": "shared",
    "generic-tag": "adhoc",
    "tag-aliases": {
        "p": "plan",
        "i": "implement",
        "r": "review",
        "a": "audit",
        "c": "check-in-prep",
    },
    "provider-aliases": {
        "local-openai": "local-openai",
        "lo": "local-openai",
        "codex": "codex",
        "cx": "codex",
        "claude": "claude",
        "cld": "claude",
        "gemini": "gemini",
        "gm": "gemini",
        "qwen": "qwen",
        "qw": "qwen",
        "copilot": "copilot",
        "cp": "copilot",
        "continue": "continue",
        "ctr": "continue",
        "cline": "cline",
        "cln": "cline",
    },
    "directive-aliases": {
        "agent": "provider",
        "subject": "id",
        "ctx": "context",
        "out": "output",
        "t": "template",
    },
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
        if key == "extends":
            continue
        merged[key] = deepcopy(value)
    return merged


def load_prompt_syntax(project_root: Path | None, profile_name: str | None = None) -> dict[str, Any]:
    syntax = deepcopy(DEFAULT_PROMPT_SYNTAX)
    if project_root is None:
        return syntax

    syntax_path = project_root / ".audiagentic" / "prompt-syntax.yaml"
    if not syntax_path.exists():
        return syntax

    payload = yaml.safe_load(syntax_path.read_text(encoding="utf-8")) or {}
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
