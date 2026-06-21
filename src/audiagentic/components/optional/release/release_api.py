"""Public API surface for the release component.

All inter-component callers and MCP wrappers import only from here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.optional.release.events import RELEASE_LEDGER_ARCHIVE_REQUESTED
from audiagentic.components.optional.release.release_please import install as _rp_install
from audiagentic.components.optional.release.release_please import manage as _rp_manage
from audiagentic.components.optional.release.release_please.finalize import render_release_docs
from audiagentic.foundation.components.ids import COMPONENT_RELEASE
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event import DeliveryMode, get_bus
from audiagentic.runtime.lifecycle.components import DEFAULT_VERSION


def get_status(project_root: Path) -> dict[str, Any]:
    """Return release-please installation status and workflow state."""
    return _rp_manage.status(project_root)


def install(
    project_root: Path,
    release_type: str = "python",
    branch: str = "main",
    python_version: str = "3.13",
    initial_version: str = DEFAULT_VERSION,
) -> dict[str, Any]:
    """Install release-please into the target project."""
    return _rp_install.install(project_root, release_type, branch, python_version, initial_version)


def update_workflow(project_root: Path, branch: str = "main", python_version: str = "3.13") -> dict[str, Any]:
    """Re-render the release workflow from the current template."""
    return _rp_manage.update_workflow(project_root, branch, python_version)


def finalize(project_root: Path, release_id: str) -> dict[str, Any]:
    """Request ledger archival then render release documents.

    Publishes a synchronous release event handled by the ledger component, then
    renders CHANGELOG.md etc. from the archived ledger state.
    After this returns, the agent should call the GitHub MCP server create_release_tag tool.
    """
    register_all_components()
    archive_result: dict[str, Any] = {}
    get_bus().publish(
        RELEASE_LEDGER_ARCHIVE_REQUESTED,
        {
            "project_root": project_root,
            "release_id": release_id,
            "result": archive_result,
        },
        metadata={
            "source_component": COMPONENT_RELEASE,
            "subject": {"kind": "release", "id": release_id},
        },
        mode=DeliveryMode.SYNC,
    )
    if not archive_result:
        raise AudiaGenticError(
            code="INT-RELEASE-001",
            kind="release",
            message="ledger archive event was not handled",
            details={"release-id": release_id},
        )
    released_ids = archive_result.get("released-event-ids") or None
    docs_result = render_release_docs(project_root, release_id, released_event_ids=released_ids)
    return {**archive_result, **docs_result}


def ensure_baseline(project_root: Path) -> dict[str, Any]:
    """Ensure the release-please baseline workflow is in place."""
    return _rp_manage.ensure_baseline(project_root)
