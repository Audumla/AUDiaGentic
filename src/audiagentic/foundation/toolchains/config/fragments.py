"""Generic managed-fragment reconciler.

Reconciles AUDiaGentic-owned named fragments (config entries, server
declarations, blocks) inside a user-owned target, tracking ownership by
stable ``managed_id`` in an injected registry so unknown/user entries are
never touched.

The engine is domain-opaque by design: payloads are ``Any`` (equality and
serialization are the store's business), storage I/O is a small
:class:`FragmentStore` of callables, the ownership registry is injected as
load/save callables, and the owner scope is an opaque key. No MCP, provider,
or component knowledge lives here — domain adapters (e.g.
``components/providers/services/mcp.py``) bind those.

Algorithm (per owner scope):
1. Remove owned entries whose managed_id is no longer desired.
2. For each desired (managed_id -> (name, payload)): refuse to overwrite a
   name owned by a *different* managed_id in the same scope (collision);
   write the payload; move ownership on rename (write new name, remove old).
3. Persist the ownership registry.

Unknown entries in the target are preserved — only entries recorded in the
ownership registry are ever removed.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FragmentStore:
    """Domain I/O for one fragment kind, as three callables.

    Attributes:
        read: ``read(path) -> dict[name, payload]`` — current entries.
        write: ``write(path, {name: payload}) -> None`` — upsert entries.
        remove: ``remove(path, name) -> bool`` — remove entry, True if removed.
    """

    read: Callable[[Path], dict[str, Any]]
    write: Callable[[Path, dict[str, Any]], None]
    remove: Callable[[Path, str], bool]


# Ownership registry I/O: full mapping of owner_scope -> {managed_id -> name}.
RegistryLoad = Callable[[], dict[str, dict[str, str]]]
RegistrySave = Callable[[dict[str, dict[str, str]]], None]


@dataclass
class ReconcileResult:
    """Structured outcome of one fragment reconciliation."""

    ok: bool
    changed: bool
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    collisions: list[dict[str, str]] = field(default_factory=list)


def reconcile_fragments(
    store: FragmentStore,
    path: Path,
    owner_scope: str,
    desired: dict[str, tuple[str, Any]],
    *,
    registry_load: RegistryLoad,
    registry_save: RegistrySave,
    managed_ids: set[str] | None = None,
) -> ReconcileResult:
    """Reconcile owned fragments at *path* toward *desired* for *owner_scope*.

    Args:
        store: Domain read/write/remove callables.
        path: Target the store operates on.
        owner_scope: Opaque registry key isolating this scope's ownership
            (e.g. a provider id).
        desired: ``managed_id -> (name, payload)`` desired state.
        registry_load / registry_save: Ownership registry I/O; the registry
            maps ``owner_scope -> {managed_id -> name}``.
        managed_ids: When given, only entries whose managed_id is in the set
            are touched (subset sync); other owned entries stay untouched.

    Returns:
        ReconcileResult with updated/removed names, cross-owner collisions
        (which mark the result not-ok), and whether anything changed.
    """
    registry = registry_load()
    scope_registry = dict(registry.get(owner_scope, {}))
    changed = False
    removed: list[str] = []
    updated: list[str] = []
    collisions: list[dict[str, str]] = []

    current = store.read(path)

    removal_source = (
        {mid: name for mid, name in scope_registry.items() if mid in managed_ids}
        if managed_ids is not None
        else dict(scope_registry)
    )

    for managed_id, old_name in list(removal_source.items()):
        if managed_id in desired:
            continue
        if old_name in current:
            if store.remove(path, old_name):
                removed.append(old_name)
                changed = True
                current.pop(old_name, None)
        scope_registry.pop(managed_id, None)

    def _owner_by_name() -> dict[str, str]:
        return {name: managed_id for managed_id, name in scope_registry.items()}

    for managed_id, (desired_name, payload) in desired.items():
        if managed_ids is not None and managed_id not in managed_ids:
            continue

        old_name = scope_registry.get(managed_id)
        owners_by_name = _owner_by_name()

        if desired_name in current and owners_by_name.get(desired_name) not in (None, managed_id):
            collisions.append({
                "managed_id": managed_id,
                "desired_name": desired_name,
                "reason": "name already owned by another managed entry",
            })
            continue

        store.write(path, {desired_name: payload})
        current[desired_name] = payload
        scope_registry[managed_id] = desired_name
        if desired_name not in updated:
            updated.append(desired_name)
        changed = True

        if old_name and old_name != desired_name and old_name in current:
            if store.remove(path, old_name):
                removed.append(old_name)
                current.pop(old_name, None)

    registry[owner_scope] = scope_registry
    registry_save(registry)

    return ReconcileResult(
        ok=not collisions,
        changed=changed,
        updated=updated,
        removed=removed,
        collisions=collisions,
    )


__all__ = [
    "FragmentStore",
    "ReconcileResult",
    "reconcile_fragments",
]
