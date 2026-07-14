"""Editor-host extensions manifest generation.

Generates the host's extensions manifest (declared in hosts.yaml)
during reconcile/install/uninstall, derived from enabled providers'
host_capabilities. Paths resolve through the host adapter — no editor
path literals here.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.providers.descriptors.base import HostCapability
from audiagentic.components.providers.services.host_adapter import get_host_adapter
from audiagentic.foundation.io import atomic_write_json, load_json_file

logger = logging.getLogger(__name__)

# User-preserved unmanaged recommendations marker
_UNMANAGED_KEY = "unmanaged-recommendations"


def _publisher_name(metadata: dict[str, Any]) -> str:
    """Extract publisher name from extension metadata variants."""
    publisher = metadata.get("publisher", "")
    if isinstance(publisher, str):
        return publisher
    if isinstance(publisher, dict):
        name = publisher.get("name", "")
        return name if isinstance(name, str) else ""
    return ""


def _read_extension_metadata(ext_id: str, *, host_id: str = "vscode") -> dict[str, Any] | None:
    """Read package.json from an installed host extension for version/metadata.

    Returns None if the extension is not installed or package.json cannot be read.
    """
    ext_dir = get_host_adapter(host_id).extension_dir()
    if not ext_dir.exists():
        return None

    ext_id_lower = ext_id.lower()
    for path in ext_dir.iterdir():
        if not path.is_dir() or path.name.startswith("."):
            continue
        # Match extension ID (format: publisher.name-version)
        if path.name.lower().startswith(ext_id_lower + "-"):
            package_json = path / "package.json"
            if package_json.exists():
                try:
                    return json.loads(package_json.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    logger.warning("Failed to read package.json for %s", ext_id, exc_info=True)
                    return None

    return None


def build_recommendations(
    extensions: tuple[HostCapability, ...],
    *,
    project_root: Path,
) -> dict[str, Any]:
    """Build the extensions.json structure from provider host capabilities.

    Merges managed recommendations with user-preserved unmanaged recommendations.
    """
    existing = _load_extensions_json(project_root)
    unmanaged = existing.get(_UNMANAGED_KEY, [])

    managed_recommendations = []
    for ext in extensions:
        rec = {
            "extension_id": ext.capability_id,
            "display_name": ext.display_name,
        }
        metadata = _read_extension_metadata(ext.capability_id)
        if metadata:
            rec["version"] = metadata.get("version", "")
            rec["publisher"] = _publisher_name(metadata)
        managed_recommendations.append(rec)

    return {
        "recommendations": [e["extension_id"] for e in managed_recommendations],
        "managed": managed_recommendations,
        _UNMANAGED_KEY: unmanaged,
    }


def _load_extensions_json(project_root: Path, *, host_id: str = "vscode") -> dict[str, Any]:
    """Load the host's existing extensions manifest if present."""
    ext_path = get_host_adapter(host_id).extensions_manifest_path(project_root)
    return load_json_file(ext_path)


def write_extensions_json(
    project_root: Path,
    extensions: tuple[HostCapability, ...],
    *,
    host_id: str = "vscode",
) -> Path:
    """Write the host's extensions manifest with managed recommendations.

    Preserves user-authored unmanaged recommendations.
    Returns the path to the written file.
    """
    ext_path = get_host_adapter(host_id).extensions_manifest_path(project_root)
    ext_path.parent.mkdir(parents=True, exist_ok=True)

    data = build_recommendations(extensions, project_root=project_root)

    vs_code_format = {
        "recommendations": data["recommendations"],
    }

    atomic_write_json(ext_path, vs_code_format)

    logger.info("Wrote extensions.json with %d recommendations", len(data["recommendations"]))
    return ext_path


def prune_extensions_json(
    project_root: Path,
    active_extensions: tuple[HostCapability, ...],
    *,
    host_id: str = "vscode",
) -> None:
    """Remove stale managed recommendations from extensions.json.

    Keeps user-preserved unmanaged recommendations.
    """
    ext_path = get_host_adapter(host_id).extensions_manifest_path(project_root)
    if not ext_path.exists():
        return

    active_ids = {ext.capability_id for ext in active_extensions}
    existing = _load_extensions_json(project_root)

    # Filter managed recommendations to only active extensions
    managed = existing.get("managed", [])
    filtered = [m for m in managed if m.get("extension_id") in active_ids]

    if filtered == managed:
        return  # No change

    # Update the file
    vs_code_format = {
        "recommendations": [m["extension_id"] for m in filtered],
    }

    atomic_write_json(ext_path, vs_code_format)

    logger.info("Pruned extensions.json to %d active recommendations", len(filtered))
