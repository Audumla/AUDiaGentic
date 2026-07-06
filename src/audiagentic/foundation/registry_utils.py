"""Generic keyed-registry utility with alias support.

Provides a reusable registry that maps string keys to typed values, with optional
alias resolution, collision detection, and test-isolation reset.

Usage:
    reg = Registry[MyDescriptor](aliases=True)
    reg.register("my-key", descriptor, aliases=["mk", "mymodel"])
    desc = reg.get("mk")  # resolves via alias

Collision policy:
    - Re-registering a DIFFERENT value under an existing key raises ValueError.
    - Idempotent re-registration of the SAME value is a silent no-op.
    - When aliases=True: registering an alias already owned by a different key
      raises ValueError. An alias colliding with an existing primary key also
      raises ValueError. Same-owner re-registration stays a silent no-op.
"""
from __future__ import annotations

import logging
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Registry(Generic[T]):
    """Generic keyed registry with optional alias support and test reset."""

    def __init__(self, aliases: bool = False) -> None:
        self._aliases_enabled = aliases
        self._items: dict[str, T] = {}
        self._aliases: dict[str, str] = {}  # alias -> key

    def register(self, key: str, value: T, aliases: list[str] | tuple[str, ...] | None = None) -> None:
        """Register a value under *key*.

        If *aliases* is provided and the registry was constructed with
        ``aliases=True``, each alias is mapped to the key. Cross-key alias
        collisions and shadow collisions (alias equals another key) raise.
        """
        # Collision check on primary key
        if key in self._items:
            if self._items[key] is value:
                # Idempotent re-registration — clean aliases and re-add
                if self._aliases_enabled:
                    self._remove_aliases_for_key(key)
                    if aliases:
                        self._add_aliases(key, aliases)
                return
            raise ValueError(
                f"key {key!r} already registered with a different value"
            )

        self._items[key] = value

        if self._aliases_enabled and aliases:
            self._add_aliases(key, aliases)

    def _remove_aliases_for_key(self, key: str) -> None:
        """Remove all aliases owned by *key* (in-place mutation)."""
        to_remove = [alias for alias, owner in self._aliases.items() if owner == key]
        for alias in to_remove:
            del self._aliases[alias]

    def _add_aliases(self, key: str, aliases: list[str] | tuple[str, ...]) -> None:
        """Add aliases for *key*, enforcing collision rules."""
        for alias in aliases:
            if alias == key:
                continue  # alias that equals the key is a no-op
            # Shadow collision: alias already exists as a primary key (owned by someone else)
            if alias in self._items and alias != key:
                raise ValueError(
                    f"alias {alias!r} shadows existing registered key"
                )
            # Cross-key collision: alias already owned by a different key
            existing_owner = self._aliases.get(alias)
            if existing_owner is not None and existing_owner != key:
                raise ValueError(
                    f"alias {alias!r} already owned by key {existing_owner!r}"
                )
            self._aliases[alias] = key

    def resolve(self, key: str) -> str | None:
        """Resolve *key* to the canonical registered key.

        Returns the key itself if it is registered directly, the owner-key
        if it is an alias, or None if not found.
        """
        if key in self._items:
            return key
        return self._aliases.get(key)

    def get(self, key: str) -> T | None:
        """Get value by key or alias."""
        resolved = self.resolve(key)
        if resolved is None:
            return None
        return self._items[resolved]

    def all(self) -> dict[str, T]:
        """Return a copy of all registered items keyed by their primary key."""
        return dict(self._items)

    def keys(self) -> tuple[str, ...]:
        """Return all registered primary keys."""
        return tuple(self._items)

    def pop(self, key: str, default: T | None = None) -> T | None:
        """Remove and return the value for *key*.

        Removes associated aliases. Returns *default* if key is not found.
        Exists for backwards compatibility with tests that access ``_registry.pop()``.
        """
        if key in self._items:
            if self._aliases_enabled:
                self._remove_aliases_for_key(key)
            return self._items.pop(key)
        return default

    def reset(self) -> None:
        """Clear all items and aliases. Used for test isolation."""
        self._items.clear()
        self._aliases.clear()
