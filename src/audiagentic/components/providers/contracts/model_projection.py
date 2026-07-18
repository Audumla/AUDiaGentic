"""Typed public contract for the model-projection automation family."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

ModelProjectionMode = Literal["plan", "apply", "prune", "status"]


@dataclass(frozen=True)
class ModelProjectionEntry:
    """A single model entry for provider config projection."""

    source_id: str
    model_id: str
    visible_name: str
    connector: str
    managed_id: str
    vendor_id: str | None = None
    endpoint: dict[str, Any] = field(default_factory=dict)
    capabilities: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    auth_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.source_id or not self.model_id or not self.connector or not self.managed_id:
            raise ValueError("source_id, model_id, connector, and managed_id are required")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "model_id": self.model_id,
            "visible_name": self.visible_name,
            "connector": self.connector,
            "managed_id": self.managed_id,
            "vendor_id": self.vendor_id,
            "endpoint": dict(self.endpoint),
            "capabilities": dict(self.capabilities),
            "limits": dict(self.limits),
            "auth_ref": self.auth_ref,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ModelProjectionEntry:
        return cls(
            source_id=str(value["source_id"]),
            model_id=str(value["model_id"]),
            visible_name=str(value.get("visible_name", "")),
            connector=str(value["connector"]),
            managed_id=str(value["managed_id"]),
            vendor_id=str(value["vendor_id"]) if value.get("vendor_id") else None,
            endpoint=dict(value.get("endpoint") or {}),
            capabilities=dict(value.get("capabilities") or {}),
            limits=dict(value.get("limits") or {}),
            auth_ref=str(value["auth_ref"]) if value.get("auth_ref") else None,
        )


@dataclass(frozen=True)
class ModelProjectionRequest:
    """Desired model entries for a provider."""

    managed_ids: tuple[str, ...]
    entries: tuple[ModelProjectionEntry, ...] = ()

    def __post_init__(self) -> None:
        ids = [entry.managed_id for entry in self.entries]
        if len(ids) != len(set(ids)):
            raise ValueError("model projection managed_ids must be unique")
        if not self.managed_ids and self.entries:
            raise ValueError("managed_ids required when entries present")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "managed_ids": list(self.managed_ids),
            "entries": [entry.to_mapping() for entry in self.entries],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ModelProjectionRequest:
        raw_entries = value.get("entries", ())
        if not isinstance(raw_entries, Sequence) or isinstance(raw_entries, (str, bytes)):
            raise ValueError("entries must be a collection")
        return cls(
            managed_ids=tuple(str(mid) for mid in value.get("managed_ids", ())),
            entries=tuple(ModelProjectionEntry.from_mapping(item) for item in raw_entries),
        )


@dataclass(frozen=True)
class ModelProjectionResult:
    ok: bool
    supported: bool
    provider_id: str = ""
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    collisions: tuple[str, ...] = ()
    skipped_connectors: tuple[dict[str, str], ...] = ()
    error_code: str | None = None
    action_needed: str | None = None
    reload_required: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "provider_id": self.provider_id,
            "added": list(self.added),
            "removed": list(self.removed),
            "updated": list(self.updated),
            "collisions": list(self.collisions),
            "skipped_connectors": list(self.skipped_connectors),
            "error_code": self.error_code,
            "action_needed": self.action_needed,
            "reload_required": self.reload_required,
        }


__all__ = [
    "ModelProjectionEntry",
    "ModelProjectionMode",
    "ModelProjectionRequest",
    "ModelProjectionResult",
]
