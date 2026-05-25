from __future__ import annotations

from pathlib import Path


def find_pi_package_root(start: Path) -> Path:
    current = start.resolve()
    while current != current.parent:
        if current.name == "audiagentic":
            return current
        current = current.parent
    raise RuntimeError(f"Could not find 'audiagentic' package root from {start}")
