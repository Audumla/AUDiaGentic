"""Planning-specific ID utilities."""

from __future__ import annotations

import json
from pathlib import Path


def sync_counter(root: Path, kind: str) -> None:
    """Advance the persisted counter to match the highest scanned ID for *kind*."""
    from ..fs.scan import scan_items
    from .config import Config

    config = Config(root)
    counter_file = config.kind_counter_file(kind)
    counter_path = root / ".audiagentic" / "planning" / "meta" / counter_file
    counter_path.parent.mkdir(parents=True, exist_ok=True)
    max_n = 0
    try:
        items = scan_items(root)
    except FileNotFoundError:
        items = []

    for item in items:
        if item.kind == kind:
            try:
                max_n = max(max_n, int(item.data["id"].split("-")[1]))
            except (IndexError, ValueError):
                pass

    counter_path.write_text(json.dumps({"counter": max_n}, indent=2), encoding="utf-8")
