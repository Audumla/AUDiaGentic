"""Requester-side conveniences over the provider-owned prompt syntax document."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.providers_api import (
    get_prompt_syntax_defaults,
)
from audiagentic.components.providers.providers_api import (
    load_prompt_syntax as _load_provider_prompt_syntax,
)


def load_no_body_required_tags(syntax: dict[str, Any]) -> set[str]:
    """Return the set of tags that do not require a prompt body."""
    tags = syntax.get("no-body-required-tags")
    if isinstance(tags, list):
        return {t for t in tags if isinstance(t, str) and t}
    return set(get_prompt_syntax_defaults()["no-body-required-tags"])


def load_review_tag(syntax: dict[str, Any]) -> str:
    """Return the canonical review tag name."""
    value = syntax.get("review-tag")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(get_prompt_syntax_defaults()["review-tag"])


def load_canonical_tags(syntax: dict[str, Any]) -> set[str]:
    """Return the set of canonical tag names from a loaded syntax dict."""
    tags = syntax.get("canonical-tags")
    if isinstance(tags, list):
        return {t for t in tags if isinstance(t, str) and t}
    return set(get_prompt_syntax_defaults()["canonical-tags"])


def load_prompt_syntax(project_root: Path | None, profile_name: str | None = None) -> dict[str, Any]:
    """Load syntax via the sanctioned provider public boundary."""
    return _load_provider_prompt_syntax(project_root, profile_name)
