"""Canonical provider-neutral prompt model."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeAlias


@dataclass(frozen=True, slots=True)
class PromptTextPart:
    text: str


@dataclass(frozen=True, slots=True)
class PromptIncludePart:
    prompt_id: str


@dataclass(frozen=True, slots=True)
class PromptFilePart:
    path: str


PromptPart: TypeAlias = PromptTextPart | PromptIncludePart | PromptFilePart


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    prompt_id: str
    description: str
    content: tuple[PromptPart, ...]
    input_schema: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.prompt_id.strip():
            raise ValueError("prompt_id is required")
        object.__setattr__(self, "content", tuple(self.content))
        if self.input_schema is not None:
            object.__setattr__(self, "input_schema", _freeze(self.input_schema))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PromptDefinition:
        prompt_id = data.get("prompt_id", data.get("prompt-id"))
        if not isinstance(prompt_id, str) or not prompt_id.strip():
            raise ValueError("prompt_id is required")
        raw_content = data.get("content")
        if raw_content is None and "system_prompt" in data:
            raw_content = [{"kind": "text", "text": data["system_prompt"]}]
        if not isinstance(raw_content, list):
            raise ValueError("content must be a list")
        content: list[PromptPart] = []
        for part in raw_content:
            if not isinstance(part, Mapping):
                raise ValueError("prompt content parts must be mappings")
            kind = part.get("kind")
            if kind == "text":
                content.append(PromptTextPart(str(part.get("text", ""))))
            elif kind == "include":
                content.append(PromptIncludePart(str(part["prompt_id"])))
            elif kind == "file":
                content.append(PromptFilePart(str(part["path"])))
            else:
                raise ValueError(f"unknown prompt content part: {kind!r}")
        schema = data.get("input_schema", data.get("input-schema"))
        if schema is not None and not isinstance(schema, Mapping):
            raise ValueError("input_schema must be a mapping")
        return cls(prompt_id.strip(), str(data.get("description") or ""), tuple(content), schema)

    def to_dict(self) -> dict[str, Any]:
        parts: list[dict[str, str]] = []
        for part in self.content:
            if isinstance(part, PromptTextPart):
                parts.append({"kind": "text", "text": part.text})
            elif isinstance(part, PromptIncludePart):
                parts.append({"kind": "include", "prompt_id": part.prompt_id})
            else:
                parts.append({"kind": "file", "path": part.path})
        return {
            "prompt_id": self.prompt_id,
            "description": self.description,
            "content": parts,
            "input_schema": _thaw(self.input_schema) if self.input_schema is not None else None,
        }


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
