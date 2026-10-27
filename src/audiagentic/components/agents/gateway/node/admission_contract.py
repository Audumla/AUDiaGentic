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
class SourceWorkspaceIdentity:
    """Caller workspace execution identity, not proof of host or file access.

    Authentication and recipient-local binding validation belong to admission.
    A root locator stays private; only its stable enrolled binding is retained.
    """

    version: int
    source_node_id: str
    workspace_id: str
    access_mode: str
    binding_sha256: str

    def __post_init__(self):
        if type(self.version) is not int or self.version != 1:
            raise invalid(1, "Source workspace version must be integer 1")
        _identifier(self.source_node_id)
        _identifier(self.workspace_id)
        if self.access_mode not in ("read-write", "read-only"):
            raise invalid(1, "Source workspace access mode is unsupported")
        if not isinstance(self.binding_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.binding_sha256):
            raise invalid(1, "Source workspace binding requires lowercase SHA256")

    def to_mapping(self) -> dict:
        return {"version": self.version, "source-node-id": self.source_node_id,
                "workspace-id": self.workspace_id, "access-mode": self.access_mode,
                "binding-sha256": self.binding_sha256}

    @classmethod
    def from_mapping(cls, value: Mapping) -> SourceWorkspaceIdentity:
        mapping = _exact(value, {"version", "source-node-id", "workspace-id", "access-mode", "binding-sha256"})
        return cls(**{key.replace("-", "_"): item for key, item in mapping.items()})


@dataclass(frozen=True)
class NodeAdmissionDescriptor:
    version: int
    server_id: str
    semantic: PromptSemanticIdentity
    policy: NodeAdmissionPolicy
    snapshot_sha256: str
    source_workspace: SourceWorkspaceIdentity | None = None

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
        if self.source_workspace is not None and type(self.source_workspace) is not SourceWorkspaceIdentity:
            raise invalid(1, "Node admission requires typed source workspace identity")

    def to_mapping(self) -> FrozenAdmissionMapping:
        mapping = {"version": self.version, "server-id": self.server_id,
                   "semantic": self.semantic.to_mapping(), "policy": self.policy.to_mapping(),
                   "snapshot-sha256": self.snapshot_sha256}
        # Preserve historical descriptor bytes and equality; absence is evidence
        # only, not a fresh-admission default or a guessed caller workspace.
        if self.source_workspace is not None:
            mapping["source-workspace"] = self.source_workspace.to_mapping()
        return _freeze(mapping)

    @classmethod
    def from_mapping(cls, value: Mapping) -> NodeAdmissionDescriptor:
        if not isinstance(value, Mapping):
            raise invalid(1, "Node admission requires a mapping")
        mapping = dict(value)
        source = mapping.pop("source-workspace", None)
        if "source-workspace" in value and source is None:
            raise invalid(1, "Explicit source workspace must be typed identity, not null")
        mapping = _exact(mapping, {"version", "server-id", "semantic", "policy", "snapshot-sha256"})
        # Bound the public envelope before canonicalization or schema diagnostics.
        semantic = PromptSemanticIdentity.from_mapping(mapping["semantic"])
        policy = NodeAdmissionPolicy.from_mapping(mapping["policy"])
        result = cls(mapping["version"], mapping["server-id"], semantic, policy, mapping["snapshot-sha256"],
                     SourceWorkspaceIdentity.from_mapping(source) if source is not None else None)
        if len(canonical_json(result.to_mapping())) > 4096:
            raise invalid(1, "Node admission descriptor exceeds the supported bound")
        return result
