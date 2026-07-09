"""Generic keyed-registry utility with alias support.

Provides a reusable registry that maps string keys to typed values, with optional
alias resolution, collision detection, lazy loading, and test-isolation reset.

Usage:
    reg = Registry[MyDescriptor](aliases=True)
    reg.register("my-key", descriptor, aliases=["mk", "mymodel"])
    desc = reg.get("mk")  # resolves via alias

Collision policy:
    - Re-registering a DIFFERENT value under an existing key raises
      AudiaGenticError VAL-REG-001.
    - Idempotent re-registration of the SAME value is a silent no-op.
    - When aliases=True: registering an alias already owned by a different key
      raises VAL-REG-002. An alias colliding with an existing primary key
      raises VAL-REG-003. Same-owner re-registration stays a silent no-op.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Generic, TypeVar

from audiagentic.foundation.contracts.errors import make_error_factory

logger = logging.getLogger(__name__)

T = TypeVar("T")
_registry_error = make_error_factory("VAL", "REG", "registry")
_REGISTRIES: list[Registry] = []


def reset_all_registries() -> None:
    """Reset every shared Registry instance."""
    for registry in list(_REGISTRIES):
        registry.reset()


class Registry(Generic[T]):
    """Generic keyed registry with optional alias support, lazy load, and reset."""

    def __init__(self, aliases: bool = False, loader: Callable[[], None] | None = None) -> None:
        self._aliases_enabled = aliases
        self._loader = loader
        self._loaded = loader is None
        self._loading = False
        self._items: dict[str, T] = {}
        self._aliases: dict[str, str] = {}  # alias -> key
        _REGISTRIES.append(self)

    def _ensure_loaded(self) -> None:
        if self._loaded or self._loading or self._loader is None:
            return
        self._loading = True
        try:
            self._loader()
            self._loaded = True
        finally:
            self._loading = False

    def is_registered(self, key: str) -> bool:
        """Check if key exists in registry without triggering lazy load."""
        return key in self._items or key in self._aliases

    def register(
        self,
        key: str,
        value: T,
        aliases: list[str] | tuple[str, ...] | None = None,
        *,
        replace: bool = False,
    ) -> None:
        """Register a value under *key*.

        If *aliases* is provided and the registry was constructed with
        ``aliases=True``, each alias is mapped to the key. Cross-key alias
        collisions and shadow collisions (alias equals another key) raise.
        """
        if replace:
            if key in self._items:
                self.pop(key)
            else:
                # Key not yet registered — skip lazy load trigger entirely.
                # This avoids recursive import chains when register(replace=True)
                # is called during initial module loading (e.g., surface modules
                # registering at import time before the registry's loader has run).
                pass

        # Collision check on primary key
        if key in self._items:
            if self._items[key] is value:
                # Idempotent re-registration — clean aliases and re-add
                if self._aliases_enabled:
                    self._remove_aliases_for_key(key)
                    if aliases:
                        self._add_aliases(key, aliases)
                return
            raise _registry_error(
                1,
                f"key {key!r} already registered with a different value",
                key=key,
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
                raise _registry_error(
                    3,
                    f"alias {alias!r} shadows existing registered key",
                    key=key,
                    alias=alias,
                )
            # Cross-key collision: alias already owned by a different key
            existing_owner = self._aliases.get(alias)
            if existing_owner is not None and existing_owner != key:
                raise _registry_error(
                    2,
                    f"alias {alias!r} already owned by key {existing_owner!r}",
                    key=key,
                    alias=alias,
                    existing_owner=existing_owner,
                )
            self._aliases[alias] = key

    def resolve(self, key: str) -> str | None:
        """Resolve *key* to the canonical registered key.

        Returns the key itself if it is registered directly, the owner-key
        if it is an alias, or None if not found.
        """
        self._ensure_loaded()
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
        self._ensure_loaded()
        return dict(self._items)

    def keys(self) -> tuple[str, ...]:
        """Return all registered primary keys."""
        self._ensure_loaded()
        return tuple(self._items)

    def pop(self, key: str, default: T | None = None, *, bypass_lazy_loader: bool = False) -> T | None:
        """Remove and return the value for *key*.

        Removes associated aliases. Returns *default* if key is not found.

        When *bypass_lazy_loader* is True and the key is not already in
        _items, skips the lazy-load trigger entirely. Use when the caller
        knows the key doesn't exist (e.g., initial registration cleanup)
        to avoid triggering recursive module imports during loading.
        Default False preserves backward compatibility: existing callers
        that rely on lazy-load-on-pop are unaffected.
        """
        if bypass_lazy_loader and key not in self._items:
            return default
        self._ensure_loaded()
        if key in self._items:
            if self._aliases_enabled:
                self._remove_aliases_for_key(key)
            return self._items.pop(key)
        return default

    def reset(self) -> None:
        """Clear all items and aliases. Used for test isolation."""
        self._items.clear()
        self._aliases.clear()
        self._loaded = self._loader is None
        self._loading = False

    def clear(self) -> None:
        """Alias for reset() for dict-like test fixtures."""
        self.reset()
