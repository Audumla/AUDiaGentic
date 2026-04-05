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
    "no-body-required-tags": [
        "ag-audit",
        "ag-check-in-prep",
    ],
    "review-tag": "ag-review",
    "implement-tag": "ag-implement",
    "canonical-tags": [
        "ag-plan",
        "ag-implement",
        "ag-review",
        "ag-audit",
        "ag-check-in-prep",
    ],
    "tag-aliases": {
        # new short forms
        "agp": "ag-plan",
        "agi": "ag-implement",
        "agr": "ag-review",
        "aga": "ag-audit",
        "agc": "ag-check-in-prep",
        # backward-compat short forms
        "p": "ag-plan",
        "i": "ag-implement",
        "r": "ag-review",
        "a": "ag-audit",
        "c": "ag-check-in-prep",
        # backward-compat full names
        "plan": "ag-plan",
        "implement": "ag-implement",
        "review": "ag-review",
        "audit": "ag-audit",
        "check-in-prep": "ag-check-in-prep",
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
        "opencode": "opencode",
        "opc": "opencode",
    },
    "directive-aliases": {
        "agent": "provider",
        "subject": "id",
        "ctx": "context",
        "out": "output",
        "t": "template",
    },
}


def load_no_body_required_tags(syntax: dict[str, Any]) -> set[str]:
    """Return the set of tags that do not require a prompt body."""
    tags = syntax.get("no-body-required-tags")
    if isinstance(tags, list):
        return {t for t in tags if isinstance(t, str) and t}
    return set(DEFAULT_PROMPT_SYNTAX["no-body-required-tags"])


def load_review_tag(syntax: dict[str, Any]) -> str:
    """Return the canonical review tag name."""
    value = syntax.get("review-tag")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(DEFAULT_PROMPT_SYNTAX["review-tag"])


def load_canonical_tags(syntax: dict[str, Any]) -> set[str]:
    """Return the set of canonical tag names from a loaded syntax dict."""
    tags = syntax.get("canonical-tags")
    if isinstance(tags, list):
        return {t for t in tags if isinstance(t, str) and t}
    return set(DEFAULT_PROMPT_SYNTAX["canonical-tags"])


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
