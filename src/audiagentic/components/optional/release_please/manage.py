from __future__ import annotations

import json
from pathlib import Path

_TEMPLATES = Path(__file__).parent / "templates"

_MANAGED_FILES = [
    "release-please-config.json",
    ".release-please-manifest.json",
    ".github/workflows/release.yml",
]


def status(project_root: Path) -> dict:
    """Return installation status of release-please in the target project."""
    files = {}
    for rel in _MANAGED_FILES:
        path = project_root / rel
        files[rel] = "present" if path.exists() else "missing"

    manifest_version: str | None = None
    manifest_path = project_root / ".release-please-manifest.json"
    if manifest_path.exists():
        try:
            manifest_version = json.loads(manifest_path.read_text(encoding="utf-8")).get(".")
        except Exception:
            pass

    config_release_type: str | None = None
    config_path = project_root / "release-please-config.json"
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            config_release_type = cfg.get("release-type") or cfg.get("packages", {}).get(".", {}).get("release-type")
        except Exception:
            pass

    installed = all(v == "present" for v in files.values())
    return {
        "installed": installed,
        "files": files,
        "current_version": manifest_version,
        "release_type": config_release_type,
    }


def update_workflow(
    project_root: Path,
    branch: str = "main",
    python_version: str = "3.13",
) -> dict:
    """Re-render the release workflow from the current template, preserving manifest version."""
    workflow_path = project_root / ".github" / "workflows" / "release.yml"
    if not workflow_path.exists():
        return {"updated": False, "reason": "workflow not present — run install first"}

    subs = {
        "__BRANCH__": branch,
        "__PYTHON_VERSION__": python_version,
    }
    template = (_TEMPLATES / "release.yml").read_text(encoding="utf-8")
    for key, value in subs.items():
        template = template.replace(key, value)

    workflow_path.write_text(template, encoding="utf-8")
    return {"updated": True, "path": str(workflow_path.relative_to(project_root))}
