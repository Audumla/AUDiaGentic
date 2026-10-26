"""Bounded public node admission identity; no queue, provider or path reads.

snapshot-sha256 identifies the protected admission snapshot, not execution
intent. Selected semantic/policy identity and sealed placement define intent.
Historical absence never manufactures fresh node admission authority.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .contracts import _identifier, canonical_json, invalid
from .preparation import PromptSemanticIdentity

_LIMIT = 2**31 - 1


class FrozenAdmissionMapping(dict):
    """JSON/schema-compatible immutable snapshot, detached from caller maps."""

    def _immutable(self, *args, **kwargs):
        raise TypeError("node admission snapshot is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _immutable

    def __deepcopy__(self, memo):
        return self


def _freeze(value: Mapping[str, Any]) -> FrozenAdmissionMapping:
    return FrozenAdmissionMapping({key: _freeze(item) if isinstance(item, Mapping) else item
                                   for key, item in value.items()})


def _exact(value: Any, names: set[str]) -> dict:
    if not isinstance(value, Mapping) or set(value) != names:
        raise invalid(1, "Node admission fields must match exactly")
    return dict(value)


@dataclass(frozen=True)
class NodeAdmissionPolicy:
    """Wire projection of NodeQueuePolicy, independently validated without imports."""

    profile_id: str
    generation: str
    config_digest: str
    pending_capacity: int
    global_capacity: int | None
    project_capacity: int | None

    def __post_init__(self):
        _identifier(self.profile_id)
        for value in (self.generation, self.config_digest):
            _identifier(value)
        for value in (self.pending_capacity, self.global_capacity, self.project_capacity):
            if value is not None and (type(value) is not int or not 1 <= value <= _LIMIT):
                raise invalid(1, "Node admission policy limits must be bounded positive integers")
        if self.pending_capacity is None:
            raise invalid(1, "Node admission pending capacity is required")

    def to_mapping(self) -> dict:
        return {"profile-id": self.profile_id, "generation": self.generation, "config-digest": self.config_digest,
                "pending-capacity": self.pending_capacity, "global-capacity": self.global_capacity,
                "project-capacity": self.project_capacity}

    @classmethod
    def from_mapping(cls, value: Mapping) -> NodeAdmissionPolicy:
        mapping = _exact(value, {"profile-id", "generation", "config-digest", "pending-capacity",
                                 "global-capacity", "project-capacity"})
        return cls(**{key.replace("-", "_"): item for key, item in mapping.items()})


@dataclass(frozen=True)
class NodeAdmissionDescriptor:
    version: int
    server_id: str
    semantic: PromptSemanticIdentity
    policy: NodeAdmissionPolicy
    snapshot_sha256: str

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise invalid(1, "Node admission version must be integer 1")
        _identifier(self.server_id)
        if type(self.semantic) is not PromptSemanticIdentity or type(self.policy) is not NodeAdmissionPolicy:
            raise invalid(1, "Node admission requires typed semantic identity and policy")
        if self.semantic.execution_profile_id != self.policy.profile_id:
            raise invalid(1, "Node semantic profile must match admission policy")
        if not isinstance(self.snapshot_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.snapshot_sha256):
            raise invalid(1, "Node admission snapshot digest must be lowercase SHA256")

    def to_mapping(self) -> FrozenAdmissionMapping:
        return _freeze({"version": self.version, "server-id": self.server_id,
                        "semantic": self.semantic.to_mapping(), "policy": self.policy.to_mapping(),
                        "snapshot-sha256": self.snapshot_sha256})

    @classmethod
    def from_mapping(cls, value: Mapping) -> NodeAdmissionDescriptor:
        mapping = _exact(value, {"version", "server-id", "semantic", "policy", "snapshot-sha256"})
        # Bound the public envelope before canonicalization or schema diagnostics.
        semantic = PromptSemanticIdentity.from_mapping(mapping["semantic"])
        policy = NodeAdmissionPolicy.from_mapping(mapping["policy"])
        result = cls(mapping["version"], mapping["server-id"], semantic, policy, mapping["snapshot-sha256"])
        if len(canonical_json(result.to_mapping())) > 4096:
            raise invalid(1, "Node admission descriptor exceeds the supported bound")
        return result
