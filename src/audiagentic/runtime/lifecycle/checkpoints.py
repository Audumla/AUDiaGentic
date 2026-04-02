"""Lifecycle checkpoint helpers."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def checkpoint_dir(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "lifecycle" / "checkpoints"


def write_checkpoint(
    project_root: Path,
    name: str,
    payload: dict[str, Any] | None = None,
    *,
    timestamp: str | None = None,
) -> Path:
    target_dir = checkpoint_dir(project_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{name}.json"

    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    checkpoint_payload = {
        "phase": name,
        "timestamp": timestamp,
        "payload": payload or {},
    }

    fd, tmp_path = tempfile.mkstemp(prefix=f"{name}.", suffix=".tmp", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(checkpoint_payload, handle, indent=2, sort_keys=True)
        os.replace(tmp_path, target_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
    return target_path
