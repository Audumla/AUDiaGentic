"""Scoped running-request registry for provider-neutral watchdog polling."""
from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any


class WatchdogRequestRegistry:
    """Process-local registry; entries are always keyed by project and request."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[tuple[Path, str], dict[str, Any]] = {}

    def register(self, project_root: Path, record: dict[str, Any]) -> None:
        request_id = record.get("request-id")
        if isinstance(request_id, str) and request_id:
            with self._lock:
                self._items[(project_root.resolve(), request_id)] = dict(record)

    def unregister(self, project_root: Path, request_id: str) -> None:
        with self._lock:
            self._items.pop((project_root.resolve(), request_id), None)

    def snapshot(self) -> tuple[tuple[Path, dict[str, Any]], ...]:
        with self._lock:
            return tuple((root, dict(record)) for (root, _), record in self._items.items())

    def diagnose(self, callback: Callable[[Path, dict[str, Any]], dict[str, Any]]) -> tuple[dict[str, Any], ...]:
        """Run one host-owned diagnostic pass over a stable scoped snapshot."""
        results: list[dict[str, Any]] = []
        for project_root, record in self.snapshot():
            updated = callback(project_root, record)
            results.append(updated)
            if updated.get("state") in {"completed", "failed", "cancelled", "interrupted"}:
                self.unregister(project_root, str(updated.get("request-id", "")))
        return tuple(results)


__all__ = ["WatchdogRequestRegistry"]

_REGISTRY = WatchdogRequestRegistry()

def watchdog_registry() -> WatchdogRequestRegistry:
    return _REGISTRY

__all__.append("watchdog_registry")
