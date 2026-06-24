"""Healing validation and fix application for propagation hierarchies."""

from __future__ import annotations

from typing import Any

from . import healing as _healing


class HealingValidator:
    """Validate and heal propagation hierarchies."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def validate_hierarchy(self, item_id: str) -> list[dict[str, Any]]:
        return _healing.validate(self._engine, item_id)

    def heal_hierarchy(self, item_id: str, auto_fix: bool = False) -> dict[str, Any]:
        return _healing.heal(self._engine, item_id, auto_fix)

    def apply_healing_fix(self, fix: dict[str, Any]) -> None:
        _healing.apply_fix(self._engine, fix)
