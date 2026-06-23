"""VS Code extensions.json generation.

Generates .vscode/extensions.json during reconcile/install/uninstall.
Derived from enabled providers' host_capabilities with host == 'vscode'.
Reads package.json from installed extensions for version/metadata.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from audiagentic.components.providers.descriptors.base import HostCapability

logger = logging.getLogger(__name__)

# User-preserved unmanaged recommendations marker
_UNMANAGED_KEY = "unmanaged-recommendations"


def _read_extension_metadata(ext_id: str) -> dict[str, Any] | None:
    """Read package.json from installed VS Code extension for version/metadata.

    Returns None if the extension is not installed or package.json cannot be read.
    """
    ext_dir = Path.home() / ".vscode" / "extensions"
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
            rec["publisher"] = metadata.get("publisher", {}).get("name", "")
        managed_recommendations.append(rec)

    return {
        "recommendations": [e["extension_id"] for e in managed_recommendations],
        "managed": managed_recommendations,
        _UNMANAGED_KEY: unmanaged,
    }


def _load_extensions_json(project_root: Path) -> dict[str, Any]:
    """Load existing extensions.json if present."""
    ext_path = project_root / ".vscode" / "extensions.json"
    if not ext_path.exists():
        return {}
    try:
        return json.loads(ext_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read extensions.json", exc_info=True)
        return {}


def write_extensions_json(
    project_root: Path,
    extensions: tuple[HostCapability, ...],
) -> Path:
    """Write .vscode/extensions.json with managed recommendations.

    Preserves user-authored unmanaged recommendations.
    Returns the path to the written file.
    """
    ext_path = project_root / ".vscode" / "extensions.json"
    ext_path.parent.mkdir(parents=True, exist_ok=True)

    data = build_recommendations(extensions, project_root=project_root)

    # Standard VS Code format
    vs_code_format = {
        "recommendations": data["recommendations"],
    }

    ext_path.write_text(
        json.dumps(vs_code_format, indent=2) + "\n",
        encoding="utf-8",
    )

    logger.info("Wrote extensions.json with %d recommendations", len(data["recommendations"]))
    return ext_path


def prune_extensions_json(
    project_root: Path,
    active_extensions: tuple[HostCapability, ...],
) -> None:
    """Remove stale managed recommendations from extensions.json.

    Keeps user-preserved unmanaged recommendations.
    """
    ext_path = project_root / ".vscode" / "extensions.json"
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
    data = {
        "recommendations": [m["extension_id"] for m in filtered],
        "managed": filtered,
        _UNMANAGED_KEY: existing.get(_UNMANAGED_KEY, []),
    }

    vs_code_format = {
        "recommendations": data["recommendations"],
    }

    ext_path.write_text(
        json.dumps(vs_code_format, indent=2) + "\n",
        encoding="utf-8",
    )

    logger.info("Pruned extensions.json to %d active recommendations", len(filtered))
