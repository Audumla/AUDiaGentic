"""Merge utilities for layered configuration.

``deep_merge`` is the legacy overlay used by ``layers.py`` callers. Settings
resolution uses ``merge_patch``: RFC 7396 JSON Merge Patch with provenance,
where ``null`` deletes and every effective value keeps the origin that set it.
CFG09 migrates ``deep_merge`` callers.
"""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .strict_yaml import json_pointer


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge overlay onto base. Lists are replaced (caller handles union)."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result

@dataclass(frozen=True)
class Origin:
    scope: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    deleted: bool = False

    def describe(self) -> str:
        where = self.file or "command line"
        if self.line is not None:
            where += f":{self.line}:{self.column}"
        return f"{'deleted by ' if self.deleted else ''}{self.scope} ({where})"


OriginOf = Callable[[str], Origin]


def merge_patch(
    target: Any,
    patch: Any,
    origins: dict[str, Origin],
    origin_of: OriginOf,
    parts: tuple[str | int, ...] = (),
) -> Any:
    """Apply ``patch`` to ``target`` (RFC 7396), updating ``origins`` in place."""
    pointer = json_pointer(parts)
    if not isinstance(patch, dict):
        _forget(origins, pointer)
        _record(patch, origins, origin_of, parts)
        return _copy(patch)
    result = dict(target) if isinstance(target, dict) else {}
    if not isinstance(target, dict):
        _forget(origins, pointer)
    if parts:
        origins.setdefault(pointer, origin_of(pointer))
    for name, value in patch.items():
        child = (*parts, name)
        child_pointer = json_pointer(child)
        if value is None:
            result.pop(name, None)
            _forget(origins, child_pointer)
            origins[child_pointer] = _tombstone(origin_of(child_pointer))
        else:
            result[name] = merge_patch(result.get(name), value, origins, origin_of, child)
    return result


def _tombstone(origin: Origin) -> Origin:
    return Origin(origin.scope, origin.file, origin.line, origin.column, deleted=True)


def _forget(origins: dict[str, Origin], pointer: str) -> None:
    for key in [key for key in origins if key == pointer or key.startswith(pointer + "/")]:
        del origins[key]


def _record(value: Any, origins: dict[str, Origin], origin_of: OriginOf, parts: tuple[str | int, ...]) -> None:
    origins[json_pointer(parts)] = origin_of(json_pointer(parts))
    if isinstance(value, dict):
        for name, child in value.items():
            _record(child, origins, origin_of, (*parts, name))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _record(child, origins, origin_of, (*parts, index))


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {name: _copy(child) for name, child in value.items()}
    if isinstance(value, list):
        return [_copy(child) for child in value]
    return value


def without_nulls(value: Any) -> Any:
    """A fragment with deletion markers removed, for fragment validation."""
    if isinstance(value, dict):
        return {name: without_nulls(child) for name, child in value.items() if child is not None}
    if isinstance(value, list):
        return [without_nulls(child) for child in value]
    return value
