"""Managed mutations of structured config files (TOML/JSON/YAML).

A :class:`ConfigPatcher` is bound to a single config file and performs targeted,
reversible edits — set/remove a nested key, add/remove an MCP server entry. Every
mutation returns an :class:`OwnedChange` recording what was touched and how to
undo it, so an :class:`~.artifact_registry.ArtifactRegistry` can prune only the
bits a recipe owns without disturbing user customizations.

Intermediate keys are auto-created on set (RV01), so patching a deep path into an
empty or partial file just works.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config_reader import UNSET, dump_config, load_config


@dataclass(frozen=True)
class OwnedChange:
    """A single reversible config mutation a recipe is responsible for.

    ``artifact_id`` is the stable ``path::dotted.key`` identifier used by the
    artifact registry. ``prior_value`` (or :data:`UNSET`) carries enough state
    to reverse the change.
    """

    artifact_id: str
    path: str
    key_path: tuple[str, ...]
    operation: str  # "set" | "remove"
    prior_value: Any = UNSET
    existed: bool = False

    @property
    def dotted(self) -> str:
        return ".".join(self.key_path)


def _artifact_id(path: str | Path, key_path: tuple[str, ...]) -> str:
    return f"{Path(path).as_posix()}::{'.'.join(key_path)}"


class ConfigPatcher:
    """Reversible key/entry mutations on one structured config file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    # --- raw key operations --------------------------------------------------

    def set_key(self, key_path: tuple[str, ...], value: Any) -> OwnedChange:
        """Set ``value`` at ``key_path``, creating intermediate tables as needed."""
        if not key_path:
            raise ValueError("key_path must be non-empty")
        data = load_config(self.path)
        node = data
        for segment in key_path[:-1]:
            child = node.get(segment)
            if not isinstance(child, dict):
                child = {}
                node[segment] = child
            node = child
        leaf = key_path[-1]
        existed = leaf in node
        prior = node.get(leaf, UNSET)
        node[leaf] = value
        dump_config(self.path, data)
        return OwnedChange(
            artifact_id=_artifact_id(self.path, key_path),
            path=self.path.as_posix(),
            key_path=tuple(key_path),
            operation="set",
            prior_value=prior,
            existed=existed,
        )

    def remove_key(self, key_path: tuple[str, ...]) -> OwnedChange:
        """Remove the key at ``key_path``. No-op (still reported) if absent."""
        if not key_path:
            raise ValueError("key_path must be non-empty")
        data = load_config(self.path)
        node: Any = data
        parents: list[dict[str, Any]] = []
        for segment in key_path[:-1]:
            if not isinstance(node, dict) or segment not in node:
                node = None
                break
            parents.append(node)
            node = node[segment]
        leaf = key_path[-1]
        prior: Any = UNSET
        existed = isinstance(node, dict) and leaf in node
        if existed:
            prior = node.pop(leaf)
            # prune now-empty parent tables we just emptied
            self._prune_empty_parents(data, key_path)
            dump_config(self.path, data)
        return OwnedChange(
            artifact_id=_artifact_id(self.path, key_path),
            path=self.path.as_posix(),
            key_path=tuple(key_path),
            operation="remove",
            prior_value=prior,
            existed=existed,
        )

    @staticmethod
    def _prune_empty_parents(data: dict[str, Any], key_path: tuple[str, ...]) -> None:
        # Walk parents from deepest to shallowest, dropping tables left empty.
        for depth in range(len(key_path) - 1, 0, -1):
            parent_path = key_path[:depth]
            node: Any = data
            ok = True
            for segment in parent_path[:-1]:
                if isinstance(node, dict) and segment in node:
                    node = node[segment]
                else:
                    ok = False
                    break
            if not ok or not isinstance(node, dict):
                break
            container = parent_path[-1]
            child = node.get(container)
            if isinstance(child, dict) and not child:
                del node[container]
            else:
                break

    # --- MCP server entries --------------------------------------------------

    def add_mcp_entry(
        self,
        server_name: str,
        entry: dict[str, Any],
        *,
        container: tuple[str, ...] = ("mcpServers",),
    ) -> OwnedChange:
        """Add/replace an MCP server entry under ``container`` (dedup by name)."""
        return self.set_key((*container, server_name), entry)

    def remove_mcp_entry(
        self,
        server_name: str,
        *,
        container: tuple[str, ...] = ("mcpServers",),
    ) -> OwnedChange:
        """Remove the named MCP server entry under ``container``."""
        return self.remove_key((*container, server_name))

    # --- reversal ------------------------------------------------------------

    def revert(self, change: OwnedChange) -> None:
        """Undo a previously applied change using its captured prior state."""
        if change.operation == "set":
            if change.existed and change.prior_value is not UNSET:
                self.set_key(change.key_path, change.prior_value)
            else:
                self.remove_key(change.key_path)
        elif change.operation == "remove":
            if change.existed and change.prior_value is not UNSET:
                self.set_key(change.key_path, change.prior_value)
        else:  # pragma: no cover - guarded by construction
            raise ValueError(f"unknown operation: {change.operation!r}")


__all__ = ["ConfigPatcher", "OwnedChange"]
