from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error


def find_package_root(start: Path) -> Path:
    """Walk up from start until a directory named 'audiagentic' is found."""
    current = start.resolve()
    while current != current.parent:
        if current.name == "audiagentic":
            return current
        current = current.parent
    raise make_error(
        prefix="RES",
        component="PATH",
        number=6,
        kind="paths",
        message=f"Could not find 'audiagentic' package root from {start}",
        details={"start": str(start)},
    )
