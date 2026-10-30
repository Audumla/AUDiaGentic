"""Apply an RFC 7396 merge patch to a settings document's text, keeping the rest of the file.

Settings files are written by people: comments, ordering and blank lines carry
meaning. The strict loader already reports where every node starts and ends, so
a patch is applied as minimal text edits to those spans instead of re-dumping
the document. Block mappings are edited in place; a flow mapping or a value that
has to change shape is rewritten as one entry. The caller checks that the result
parses to exactly ``merged(old, patch)`` and refuses a layout this cannot edit.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from .merge import merged
from .strict_yaml import resolve_plain_scalar

_PLAIN_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")


@dataclass
class _Entry:
    key: str
    key_start: int
    key_end: int
    key_line: int
    value: _Node


@dataclass
class _Node:
    kind: str  # "scalar" | "map" | "seq"
    start: int
    end: int
    line: int
    last_line: int
    flow: bool = False
    entries: list[_Entry] = field(default_factory=list)


def _build(events: list[yaml.Event]) -> _Node | None:
    position = 0

    def node() -> _Node:
        nonlocal position
        event = events[position]
        position += 1
        start, end = event.start_mark, event.end_mark
        if isinstance(event, yaml.ScalarEvent):
            last = end.line - 1 if end.column == 0 and end.index > start.index else end.line
            return _Node("scalar", start.index, end.index, start.line, last)
        flow = bool(event.flow_style)
        if isinstance(event, yaml.SequenceStartEvent):
            result = _Node("seq", start.index, start.index, start.line, start.line, flow)
            while not isinstance(events[position], yaml.SequenceEndEvent):
                result.last_line = max(result.last_line, node().last_line)
            end_event = events[position]
            position += 1
            result.end = end_event.end_mark.index
            result.last_line = max(result.last_line, end_event.end_mark.line) if flow else result.last_line
            return result
        result = _Node("map", start.index, start.index, start.line, start.line, flow)
        while not isinstance(events[position], yaml.MappingEndEvent):
            key_event = events[position]
            key = node()
            value = node()
            result.entries.append(
                _Entry(key_event.value, key.start, key.end, key.line, value)
            )
            result.last_line = max(result.last_line, value.last_line)
        end_event = events[position]
        position += 1
        result.end = end_event.end_mark.index
        if flow:
            result.last_line = max(result.last_line, end_event.end_mark.line)
        return result

    position = 1  # StreamStart
    if isinstance(events[position], yaml.StreamEndEvent):
        return None
    position += 1  # DocumentStart
    return node()


def _scalar(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _key(name: str) -> str:
    return name if _PLAIN_KEY.match(name) and resolve_plain_scalar(name) == name else json.dumps(name)


def _render(mapping: dict[str, Any], indent: int) -> list[str]:
    lines: list[str] = []
    for name, value in mapping.items():
        if isinstance(value, dict) and value:
            lines.append(f"{' ' * indent}{_key(name)}:")
            lines.extend(_render(value, indent + 2))
        else:
            lines.append(f"{' ' * indent}{_key(name)}: {_scalar(value)}")
    return lines


class _Editor:
    def __init__(self, text: str):
        self.text = text
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.starts = [0]
        for match in re.finditer(r"\n", text):
            self.starts.append(match.end())
        self.edits: list[tuple[int, int, str]] = []

    def line_start(self, line: int) -> int:
        return self.starts[line] if line < len(self.starts) else len(self.text)

    def line_end(self, line: int) -> int:
        """Offset just past the line's newline (or the end of the text)."""
        return self.line_start(line + 1)

    def block(self, lines: list[str]) -> str:
        return "".join(line + self.newline for line in lines)

    def column(self, entry: _Entry) -> int:
        return entry.key_start - self.line_start(entry.key_line)

    def rewrite_entry(self, entry: _Entry, new: Any) -> None:
        lines = _render({entry.key: new}, self.column(entry))
        self.edits.append((self.line_start(entry.key_line), self.line_end(entry.value.last_line), self.block(lines)))

    def set_value(self, entry: _Entry, new: Any) -> None:
        value = entry.value
        multiline = value.last_line > entry.key_line
        if (isinstance(new, dict) and new) or multiline:
            self.rewrite_entry(entry, new)
        elif value.start == value.end:  # `key:` with nothing after the colon
            colon = self.text.index(":", entry.key_end)
            self.edits.append((colon + 1, colon + 1, " " + _scalar(new)))
        else:
            self.edits.append((value.start, value.end, _scalar(new)))

    def patch_map(self, node: _Node, old: dict[str, Any], patch: dict[str, Any]) -> None:
        indent = self.column(node.entries[0])
        added: dict[str, Any] = {}
        for name, change in patch.items():
            entry = next((e for e in node.entries if e.key == name), None)
            if entry is None:
                kept = merged(None, change) if change is not None else None
                if kept is not None:
                    added[name] = kept
            elif change is None:
                self.edits.append((self.line_start(entry.key_line), self.line_end(entry.value.last_line), ""))
            else:
                result = merged(old.get(name), change)
                value = entry.value
                if isinstance(change, dict) and isinstance(old.get(name), dict) and value.kind == "map" \
                        and not value.flow and result and value.entries:
                    self.patch_map(value, old[name], change)
                else:
                    self.set_value(entry, result)
        if added:
            at = self.line_end(node.entries[-1].value.last_line)
            lead = "" if self.text[at - 1 : at] == "\n" else self.newline
            self.edits.append((at, at, lead + self.block(_render(added, indent))))

    def apply(self) -> str:
        # Bottom-up so offsets stay valid. Insertions at one offset are applied latest-first, which
        # leaves the earliest recorded (the innermost mapping's) text first.
        text = self.text
        order = sorted(enumerate(self.edits), key=lambda item: (item[1][0], item[1][1], item[0]), reverse=True)
        for _, (start, end, replacement) in order:
            text = text[:start] + replacement + text[end:]
        return text


def patch_text(text: str, old: dict[str, Any], patch: dict[str, Any]) -> str:
    """``text`` with ``patch`` applied; ``old`` is what ``text`` parses to."""
    new = merged(old, patch)
    root = _build(list(yaml.parse(text, Loader=yaml.SafeLoader)))
    editor = _Editor(text)
    if root is None or root.kind != "map" or root.flow or not root.entries:
        body = editor.block(_render(new, 0)) if new else "{}" + editor.newline
        if root is not None and root.kind == "map" and (root.flow or not root.entries):
            return text[: root.start] + body.rstrip("\r\n") + text[root.end:]
        lead = "" if not text or text.endswith("\n") else editor.newline
        return text + lead + body
    editor.patch_map(root, old, patch)
    result = editor.apply()
    if not new:  # every entry was deleted: keep the comments, state the empty mapping
        return result.rstrip("\r\n") + editor.newline + "{}" + editor.newline
    return result
