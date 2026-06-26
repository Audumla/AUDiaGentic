"""Generic typed registry for descriptors.

Provides a parameterized registry that maps string IDs to typed descriptor
instances. Used by provider descriptors, component descriptors, and any
other descriptor type.

The registry is generic: ``DescriptorRegistry[T]`` holds instances of type T.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from .loader import DescriptorSpec, iter_descriptor_files, load_descriptor

T = TypeVar("T")


class DescriptorRegistry:
    """Generic registry for typed descriptors.

    Maps string IDs to descriptor instances. Supports YAML-based loading
    with a DescriptorSpec.

    Attributes:
        _registry: Internal ID-to-descriptor mapping.
    """

    def __init__(self) -> None:
        self._registry: dict[str, object] = {}

    def register(self, id: str, descriptor: T) -> None:
        """Register a descriptor by ID."""
        self._registry[id] = descriptor

    def get(self, id: str) -> T | None:
        """Get descriptor by ID, or None if not found."""
        result = self._registry.get(id)
        if result is None:
            return None
        return result  # type: ignore[return-value]

    def all(self) -> dict[str, T]:
        """Return a copy of all registered descriptors."""
        return dict(self._registry)  # type: ignore[return-value]

    def ids(self) -> tuple[str, ...]:
        """Return all registered IDs."""
        return tuple(self._registry)

    def load_yaml_directory(
        self,
        directory: Path,
        spec: DescriptorSpec,
        id_field: str = "provider_id",
    ) -> None:
        """Load all YAML descriptors from a directory.

        Each YAML file is loaded via the spec, and the value of *id_field*
        is used as the registry key.

        Args:
            directory: Directory containing YAML files.
            spec: Field specification for the descriptor type.
            id_field: Name of the field that contains the descriptor ID.
        """
        for path in iter_descriptor_files(directory):
            descriptor = load_descriptor(path, spec)
            desc_id = descriptor.get(id_field) if isinstance(descriptor, dict) else getattr(descriptor, id_field, None)
            if desc_id:
                self.register(desc_id, descriptor)

    def alias_map(
        self,
        aliases_field: str = "prompt_aliases",
    ) -> dict[str, str]:
        """Build an alias-to-ID mapping from descriptor fields.

        Args:
            aliases_field: Name of the field containing alias tuples.

        Returns:
            Dict mapping each alias (and canonical ID) to the descriptor ID.
        """
        aliases: dict[str, str] = {}
        for desc_id, descriptor in self._registry.items():
            aliases[str(desc_id)] = str(desc_id)
            alias_list = getattr(descriptor, aliases_field, None)
            if alias_list:
                for alias in alias_list:
                    aliases[alias] = str(desc_id)
        return aliases

    def query(
        self,
        predicate: Callable[[T], bool],
    ) -> list[T]:
        """Return all descriptors matching a predicate."""
        return [d for d in self._registry.values() if predicate(d)]  # type: ignore[list-item, return-value]
