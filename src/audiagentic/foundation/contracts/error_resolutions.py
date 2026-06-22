"""Load error resolution definitions from component config files.

Scans each component's config directory for ``error-resolutions.yaml`` and
registers the error codes with the resolution registry.

File format (YAML):
    VAL-PROJFILE-001: "This tool only reads files inside the .audiagentic/ directory."
    RES-PROJFILE-001: "The file was not found at the specified path."

Resolution files are optional — components without them simply have no
agent-facing resolutions.
"""
from __future__ import annotations

import logging
from pathlib import Path

from audiagentic.foundation.contracts.errors import register_error_resolution
from audiagentic.foundation.io import load_yaml_file

logger = logging.getLogger(__name__)


def load_error_resolutions_from_component(component_id: str, config_dir: Path) -> int:
    """Load error resolutions from a component's ``error-resolutions.yaml``.

    Returns the number of resolutions registered.
    """
    resolutions_path = config_dir / f"{component_id}" / "error-resolutions.yaml"
    if not resolutions_path.exists():
        return 0

    data = load_yaml_file(resolutions_path)
    count = 0
    for code, resolution in data.items():
        if not isinstance(code, str) or not isinstance(resolution, str):
            logger.warning(
                "Skipping invalid entry in %s: expected string key and value, got %r: %r",
                resolutions_path, code, resolution,
            )
            continue
        register_error_resolution(code, resolution)
        count += 1
    return count


def load_all_error_resolutions(config_dirs: list[Path] | None = None) -> None:
    """Load error resolutions from all registered component config directories."""
    targets = config_dirs or [Path(__file__).resolve().parents[2] / "config" / "components"]
    for config_dir in targets:
        if not config_dir.exists():
            continue
        for component_dir in sorted(config_dir.glob("*")):
            if not component_dir.is_dir():
                continue
            component_id = component_dir.name
            # Skip top-level single-file components (e.g. coding-lsp.yaml)
            # Only process subdirectory-based components that have error-resolutions.yaml
            try:
                load_error_resolutions_from_component(component_id, config_dir)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to load error resolutions for %s", component_id,
                    exc_info=True,
                )
