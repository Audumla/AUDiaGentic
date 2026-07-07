"""Action registry — in-process store of all loaded ActionDescriptors."""
from __future__ import annotations

from audiagentic.foundation.registry_utils import Registry

from .base import ActionDescriptor


def _load_tags() -> None:
    from .loader import load_all_tags  # noqa: PLC0415
    load_all_tags()


_registry: Registry[ActionDescriptor] = Registry(loader=_load_tags)


def register(descriptor: ActionDescriptor) -> None:
    _registry.register(descriptor.tag_id, descriptor, replace=True)


def get_tag(tag_id: str) -> ActionDescriptor | None:
    return _registry.get(tag_id)


def all_tags() -> dict[str, ActionDescriptor]:
    """Return all actions, triggering YAML discovery on first call."""
    return _registry.all()


def canonical_tag_ids() -> list[str]:
    return sorted(_registry.keys())


def tag_alias_map() -> dict[str, str]:
    """Return flat alias -> tag_id map across all registered actions."""
    result: dict[str, str] = {}
    for tag_id, descriptor in _registry.all().items():
        result[tag_id] = tag_id
        for alias in descriptor.aliases:
            result[alias] = tag_id
    return result


def generic_tag_id() -> str | None:
    for descriptor in _registry.all().values():
        if descriptor.is_generic_tag:
            return descriptor.tag_id
    return None


def review_tag_id() -> str | None:
    for descriptor in _registry.all().values():
        if descriptor.is_review_tag:
            return descriptor.tag_id
    return None


def no_body_required_tag_ids() -> set[str]:
    return {d.tag_id for d in _registry.all().values() if not d.requires_body}
