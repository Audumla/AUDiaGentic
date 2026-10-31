"""Strict YAML 1.2 core loader for human-authored settings files.

Only PyYAML's event parser is used. PyYAML's resolvers and constructors never
run, so YAML 1.1 implicit typing (``yes``/``on``/``0755``/dates), tags and
object construction cannot apply. Scalars resolve with the YAML 1.2 core
schema restricted to JSON-compatible values; anchors, aliases, explicit tags,
duplicate or non-string keys and multiple documents are rejected with the
file, line and column of the offending node.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.contracts.errors import make_error_factory

settings_error = make_error_factory("CFG", "SET", "config")

MAX_BYTES = 1024 * 1024
MAX_DEPTH = 64

_NULL = re.compile(r"(?:~|null|Null|NULL|)\Z")
_BOOL = {"true": True, "True": True, "TRUE": True, "false": False, "False": False, "FALSE": False}
_INT10 = re.compile(r"[-+]?[0-9]+\Z")
_INT8 = re.compile(r"0o[0-7]+\Z")
_INT16 = re.compile(r"0x[0-9a-fA-F]+\Z")
_FLOAT = re.compile(r"[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?\Z")
_NON_JSON_FLOAT = re.compile(r"(?:[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))\Z")


@dataclass(frozen=True)
class Position:
    line: int
    column: int


@dataclass(frozen=True)
class LoadedDocument:
    path: Path
    data: dict[str, Any]
    positions: dict[str, Position]  # JSON pointer of each value -> where it starts


def json_pointer(parts: tuple[str | int, ...]) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def load_settings_file(path: Path) -> LoadedDocument:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise settings_error(1, "Cannot read settings file", file=str(path), reason=error.strerror) from None
    if len(raw) > MAX_BYTES:
        raise settings_error(1, "Settings file is larger than 1 MiB", file=str(path), bytes=len(raw))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise settings_error(1, "Settings file is not valid UTF-8", file=str(path), byte=error.start) from None
    return load_settings_text(text, path)


def load_settings_text(text: str, path: Path) -> LoadedDocument:
    try:
        events = list(yaml.parse(text, Loader=yaml.SafeLoader))
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        raise settings_error(
            2, f"YAML syntax error: {error.problem or error.context}", file=str(path),
            line=mark.line + 1 if mark else None, column=mark.column + 1 if mark else None,
        ) from None
    except yaml.YAMLError as error:
        raise settings_error(2, f"YAML syntax error: {error}", file=str(path)) from None
    builder = _Builder(events, path)
    data = builder.document()
    return LoadedDocument(path, data, builder.positions)


def resolve_plain_scalar(value: str) -> Any:
    """YAML 1.2 core schema for plain scalars, limited to JSON-compatible values."""
    if _NULL.match(value):
        return None
    if value in _BOOL:
        return _BOOL[value]
    if _INT10.match(value):
        return int(value, 10)
    if _INT8.match(value):
        return int(value[2:], 8)
    if _INT16.match(value):
        return int(value[2:], 16)
    if _FLOAT.match(value):
        return float(value)
    if _NON_JSON_FLOAT.match(value):
        raise ValueError("infinity and NaN are not allowed")
    return value


class _Builder:
    def __init__(self, events: list[yaml.Event], path: Path):
        self.events = events
        self.index = 0
        self.path = path
        self.positions: dict[str, Position] = {}

    def _next(self) -> yaml.Event:
        event = self.events[self.index]
        self.index += 1
        return event

    def _fail(self, message: str, event: yaml.Event, parts: tuple[str | int, ...]) -> None:
        mark = event.start_mark
        raise settings_error(
            3, message, file=str(self.path), line=mark.line + 1, column=mark.column + 1,
            pointer=json_pointer(parts) or "/",
        )

    def document(self) -> dict[str, Any]:
        self._next()  # StreamStartEvent
        if isinstance(self.events[self.index], yaml.StreamEndEvent):
            return {}
        self._next()  # DocumentStartEvent
        start = self.events[self.index]
        data = self._node((), 0)
        self._next()  # DocumentEndEvent
        following = self.events[self.index]
        if isinstance(following, yaml.DocumentStartEvent):
            self._fail("Settings files must contain a single YAML document", following, ())
        if data is None:
            return {}
        if not isinstance(data, dict):
            self._fail("Settings file must contain a mapping at the top level", start, ())
        return data

    def _check_node(self, event: yaml.Event, parts: tuple[str | int, ...], depth: int) -> None:
        if isinstance(event, yaml.AliasEvent):
            self._fail("YAML aliases are not allowed in settings", event, parts)
        if depth > MAX_DEPTH:
            self._fail(f"Settings nesting deeper than {MAX_DEPTH} levels", event, parts)
        if getattr(event, "anchor", None) is not None:
            self._fail("YAML anchors are not allowed in settings", event, parts)
        if getattr(event, "tag", None) is not None:
            self._fail("YAML tags are not allowed in settings", event, parts)

    def _node(self, parts: tuple[str | int, ...], depth: int) -> Any:
        event = self._next()
        self._check_node(event, parts, depth)
        self.positions[json_pointer(parts)] = Position(event.start_mark.line + 1, event.start_mark.column + 1)
        if isinstance(event, yaml.ScalarEvent):
            return self._scalar(event, parts)
        if isinstance(event, yaml.SequenceStartEvent):
            items = []
            while not isinstance(self.events[self.index], yaml.SequenceEndEvent):
                items.append(self._node((*parts, len(items)), depth + 1))
            self._next()
            return items
        if isinstance(event, yaml.MappingStartEvent):
            mapping: dict[str, Any] = {}
            while not isinstance(self.events[self.index], yaml.MappingEndEvent):
                key_event = self._next()
                self._check_node(key_event, parts, depth + 1)
                if not isinstance(key_event, yaml.ScalarEvent):
                    self._fail("Settings keys must be strings", key_event, parts)
                key = self._scalar(key_event, parts) if key_event.style is None else key_event.value
                if not isinstance(key, str) or not key:
                    self._fail("Settings keys must be non-empty strings", key_event, parts)
                if key in mapping:
                    self._fail(f"Duplicate key {key!r}", key_event, (*parts, key))
                mapping[key] = self._node((*parts, key), depth + 1)
            self._next()
            return mapping
        self._fail(f"Unexpected YAML event {type(event).__name__}", event, parts)
        return None

    def _scalar(self, event: yaml.ScalarEvent, parts: tuple[str | int, ...]) -> Any:
        if event.style is not None:  # quoted or block scalars are always strings
            return event.value
        try:
            return resolve_plain_scalar(event.value)
        except ValueError as error:
            self._fail(f"Invalid value: {error}", event, parts)
            return None
