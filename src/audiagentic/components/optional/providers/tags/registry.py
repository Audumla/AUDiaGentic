"""Tag registry — in-process store of all loaded TagDescriptors."""
from __future__ import annotations

from .base import TagDescriptor

_registry: dict[str, TagDescriptor] = {}
_loaded: bool = False


def register(descriptor: TagDescriptor) -> None:
    _registry[descriptor.tag_id] = descriptor


def get_tag(tag_id: str) -> TagDescriptor | None:
    return _registry.get(tag_id)


def all_tags() -> dict[str, TagDescriptor]:
    return dict(_registry)


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    from .loader import load_all_tags  # noqa: PLC0415
    load_all_tags()
    _loaded = True


def all_tags_loaded() -> dict[str, TagDescriptor]:
    """Return all tags, triggering YAML discovery on first call."""
    _ensure_loaded()
    return all_tags()


def canonical_tag_ids() -> list[str]:
    _ensure_loaded()
    return sorted(_registry)


def tag_alias_map() -> dict[str, str]:
    """Return flat alias -> tag_id map across all registered tags."""
    _ensure_loaded()
    result: dict[str, str] = {}
    for tag_id, descriptor in _registry.items():
        result[tag_id] = tag_id   # identity alias
        for alias in descriptor.aliases:
            result[alias] = tag_id
    return result


def generic_tag_id() -> str | None:
    _ensure_loaded()
    for descriptor in _registry.values():
        if descriptor.is_generic_tag:
            return descriptor.tag_id
    return None


def review_tag_id() -> str | None:
    _ensure_loaded()
    for descriptor in _registry.values():
        if descriptor.is_review_tag:
            return descriptor.tag_id
    return None


def no_body_required_tag_ids() -> set[str]:
    _ensure_loaded()
    return {d.tag_id for d in _registry.values() if not d.requires_body}
