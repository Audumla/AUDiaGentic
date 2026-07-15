"""Typed public contract scaffold for generated provider surfaces."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass


GeneratedSurfaceMode = str  # plan | apply | prune | status


@dataclass(frozen=True)
class GeneratedSurfaceRequest:
    """Caller-owned desired surface scope.

    Contribution ids are semantic identities only. Renderers remain the sole
    owner of provider-native paths, block formatting, and file mechanics.
    """

    ownership_scope: str
    contribution_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.ownership_scope:
            raise ValueError("ownership_scope is required")
        if not self.contribution_ids or any(not item for item in self.contribution_ids):
            raise ValueError("contribution_ids must be non-empty")
        if len(self.contribution_ids) != len(set(self.contribution_ids)):
            raise ValueError("contribution_ids must be unique")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> GeneratedSurfaceRequest:
        raw_ids = value.get("contribution_ids")
        if not isinstance(raw_ids, Sequence) or isinstance(raw_ids, (str, bytes)):
            raise ValueError("contribution_ids must be a sequence")
        if any(not isinstance(item, str) for item in raw_ids):
            raise ValueError("contribution_ids must contain strings")
        return cls(
            ownership_scope=str(value["ownership_scope"]),
            contribution_ids=tuple(raw_ids),
        )

    def to_mapping(self) -> dict[str, object]:
        return {
            "ownership_scope": self.ownership_scope,
            "contribution_ids": list(self.contribution_ids),
        }


@dataclass(frozen=True)
class GeneratedSurfaceResult:
    """Outcome for one provider's generated-surface operation."""

    ok: bool
    supported: bool
    changed: bool = False
    planned: bool = False
    written_paths: tuple[str, ...] = ()
    removed_paths: tuple[str, ...] = ()
    managed_block_ids: tuple[str, ...] = ()
    collision_ids: tuple[str, ...] = ()
    action_needed: str | None = None
    error_code: str | None = None

    def to_mapping(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "supported": self.supported,
            "changed": self.changed,
            "planned": self.planned,
            "written_paths": list(self.written_paths),
            "removed_paths": list(self.removed_paths),
            "managed_block_ids": list(self.managed_block_ids),
            "collision_ids": list(self.collision_ids),
            "action_needed": self.action_needed,
            "error_code": self.error_code,
        }


__all__ = ["GeneratedSurfaceMode", "GeneratedSurfaceRequest", "GeneratedSurfaceResult"]
