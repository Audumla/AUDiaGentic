"""Editor-host settings manifest merging (e.g. VS Code's .vscode/settings.json).

Mirrors extensions_json.py's isolation: all host-specific filesystem access
routes through the host adapter (services/host/host_adapter.py) — no editor
path literals here. Callers own the managed key/value shape (e.g. "yaml.*"
keys); this module only merges them into the host's settings file without
disturbing unrelated user-authored keys.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.providers.services.host.host_adapter import get_host_adapter
from audiagentic.foundation.io import atomic_write_json, load_json_file

logger = logging.getLogger(__name__)


def write_host_settings(
    project_root: Path,
    updates: dict[str, Any],
    *,
    host_id: str = "vscode",
) -> Path:
    """Merge managed key/value pairs into the host's settings manifest.

    Shallow top-level merge: each key in ``updates`` overwrites the same key
    in the existing file, everything else (user-authored settings) is left
    untouched. Callers are expected to use fully-namespaced keys (e.g.
    "yaml.validate") so managed and unmanaged settings never collide.
    """
    settings_path = get_host_adapter(host_id).settings_manifest_path(project_root)
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_json_file(settings_path)
    existing.update(updates)
    atomic_write_json(settings_path, existing, sort_keys=True)

    logger.info("Wrote %d managed setting(s) to %s", len(updates), settings_path)
    return settings_path


__all__ = ["write_host_settings"]
