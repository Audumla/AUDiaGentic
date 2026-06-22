"""Alias and directive normalization helpers for tagged interactive prompts."""
from __future__ import annotations

import logging

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)

SHORT_TAG_PROVIDER_SEPARATOR = "-"


def _split_tag_and_provider(
    raw_tag: str, *, tag_aliases: dict[str, str], generic_tag: str, allowed_tags: set[str]
) -> tuple[str, str | None]:
    tag_token = raw_tag[1:]
    if SHORT_TAG_PROVIDER_SEPARATOR not in tag_token:
        return tag_token, None
    tag_part, provider_part = tag_token.split(SHORT_TAG_PROVIDER_SEPARATOR, 1)
    if tag_part in tag_aliases or tag_part in allowed_tags or tag_part == generic_tag:
        return tag_part, provider_part or None
    return tag_token, None


def _normalize_alias_map(alias_map: dict[str, str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    if not isinstance(alias_map, dict):
        return normalized
    for raw_key, raw_value in alias_map.items():
        if isinstance(raw_key, str) and isinstance(raw_value, str) and raw_key:
            normalized[raw_key] = raw_value
    return normalized


def _normalize_directives(raw_directives: dict[str, str], alias_map: dict[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for raw_key, value in raw_directives.items():
        key = alias_map.get(raw_key, raw_key)
        if key in normalized:
            raise AudiaGenticError(
                code="VAL-PPARSE-005",
                kind="agent-jobs",
                message="duplicate prompt directive",
                details={"directive": key},
            )
        normalized[key] = value
    return normalized


def _normalize_provider(value: str | None, alias_map: dict[str, str]) -> str | None:
    if value is None:
        return None
    return alias_map.get(value, value)
