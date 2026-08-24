"""Typed boundary contracts for the canonical Agents document."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, TypeAlias

from audiagentic.components.agents.models.prompt_definition import PromptDefinition

ConfigKind: TypeAlias = str


@dataclass(frozen=True, slots=True)
class AgentsConfigDocument:
    contract_version: str
    prompts: tuple[dict[str, Any] | PromptDefinition, ...]
    roles: tuple[dict[str, Any], ...]
    execution_profiles: tuple[dict[str, Any], ...]
    agents: tuple[dict[str, Any], ...]
    triggers: tuple[dict[str, Any], ...] = ()
    # Retained as a read-only compatibility slot for callers constructing
    # older v2 documents positionally.  It is deliberately not serialized,
    # validated, or consulted by execution; prompt definitions are the sole
    # public prompt authority now.
    prompt_profiles: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("roles", "execution_profiles", "agents", "triggers"):
            values = tuple(_freeze(value) for value in getattr(self, field_name))
            object.__setattr__(self, field_name, values)

    def to_mapping(self) -> dict[str, Any]:
        def encode(values: tuple[Any, ...], identifier: str) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for raw in values:
                item = raw.to_dict() if hasattr(raw, "to_dict") else _thaw(raw)
                item_id = item.pop(identifier, None)
                if not isinstance(item_id, str) or not item_id:
                    raise ValueError(f"{identifier} is required")
                result[item_id] = item
            return result

        return {
            "contract-version": self.contract_version,
            "prompts": encode(self.prompts, "prompt_id"),
            "roles": encode(self.roles, "role_id"),
            "execution_profiles": encode(self.execution_profiles, "profile_id"),
            "agents": encode(self.agents, "agent_id"),
            "triggers": encode(self.triggers, "trigger_id"),
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> AgentsConfigDocument:
        return cls(
            contract_version=str(data.get("contract-version", "v2")),
            prompts=tuple(PromptDefinition.from_dict(item) for item in _collection(data, "prompts", "prompt_id")),
            roles=tuple(_collection(data, "roles", "role_id")),
            execution_profiles=tuple(_collection(data, "execution_profiles", "profile_id")),
            agents=tuple(_collection(data, "agents", "agent_id")),
            triggers=tuple(_collection(data, "triggers", "trigger_id")),
            # Older documents may still contain this key; ignore it so a
            # subsequent atomic write removes the stale public collection.
            prompt_profiles=(),
        )


def _collection(data: dict[str, Any], key: str, identifier: str) -> list[dict[str, Any]]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a mapping keyed by {identifier}")
    entries: list[dict[str, Any]] = []
    for item_id, body in value.items():
        if not isinstance(item_id, str) or not isinstance(body, dict):
            raise ValueError(f"{key} must map string ids to mappings")
        embedded = body.get(identifier, body.get(identifier.replace("_", "-")))
        if embedded is not None and embedded != item_id:
            raise ValueError(f"{key}[{item_id!r}] has conflicting embedded {identifier}")
        entry = dict(body)
        entry[identifier] = item_id
        entries.append(entry)
    return entries


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, MappingProxyType):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    if isinstance(value, dict):
        return {key: _thaw(item) for key, item in value.items()}
    return value
