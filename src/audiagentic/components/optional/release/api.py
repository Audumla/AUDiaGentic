"""Public API surface for the release component.

All inter-component callers and MCP wrappers import only from here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.optional.release.release_please import install as _rp_install
from audiagentic.components.optional.release.release_please import manage as _rp_manage
from audiagentic.components.optional.release.release_please.finalize import render_release_docs


def get_status(project_root: Path) -> dict[str, Any]:
    """Return release-please installation status and workflow state."""
    return _rp_manage.status(project_root)


def install(
    project_root: Path,
    release_type: str = "python",
    branch: str = "main",
    python_version: str = "3.13",
    initial_version: str = "0.1.0",
) -> dict[str, Any]:
    """Install release-please into the target project."""
    return _rp_install.install(project_root, release_type, branch, python_version, initial_version)


def update_workflow(project_root: Path, branch: str = "main", python_version: str = "3.13") -> dict[str, Any]:
    """Re-render the release workflow from the current template."""
    return _rp_manage.update_workflow(project_root, branch, python_version)


def finalize(project_root: Path, release_id: str) -> dict[str, Any]:
    """Archive current ledger then render release documents.

    Calls ledger.api.archive_current then renders CHANGELOG.md etc.
    After this returns, the agent should call the GitHub MCP server create_release_tag tool.
    """
    from audiagentic.components.optional.ledger.api import archive_current
    archive_result = archive_current(project_root, release_id)
    docs_result = render_release_docs(project_root, release_id)
    return {**archive_result, **docs_result}


def ensure_baseline(project_root: Path) -> dict[str, Any]:
    """Ensure the release-please baseline workflow is in place."""
    return _rp_manage.ensure_baseline(project_root)
