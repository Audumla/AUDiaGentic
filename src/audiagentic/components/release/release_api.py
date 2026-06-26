"""Public API surface for the release component.

All inter-component callers and MCP wrappers import only from here.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from audiagentic.components.release.events import RELEASE_LEDGER_ARCHIVE_REQUESTED
from audiagentic.components.release.github_auth import (
    clear_token as _clear_token,
)
from audiagentic.components.release.github_auth import (
    github_auth_status,
    github_authenticate,
)
from audiagentic.components.release.github_auth import (
    load_token as _load_token,
)
from audiagentic.components.release.github_auth import (
    poll_device_flow as _poll_device_flow,
)
from audiagentic.components.release.github_auth import (
    start_device_flow as _start_device_flow,
)
from audiagentic.components.release.release_please import install as _rp_install
from audiagentic.components.release.release_please import manage as _rp_manage
from audiagentic.components.release.release_please.finalize import render_release_docs
from audiagentic.foundation.components.ids import COMPONENT_RELEASE
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event import DeliveryMode, get_bus
from audiagentic.runtime.lifecycle.components import DEFAULT_VERSION
from audiagentic.runtime.update import GITHUB_REPO

_RELEASE_WORKFLOW_ID = "release.yml"


def get_status(project_root: Path, branch: str = "main", python_version: str = "3.13") -> dict[str, Any]:
    """Return release-please installation status and workflow state."""
    return _rp_manage.status(project_root, branch, python_version)


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
    from audiagentic.components.ledger import ledger_events as _ledger_events

    _ledger_events.register()
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
            message="ledger archive event was not handled — ledger_events.register() may not have been called",
            details={"release-id": release_id},
        )
    released_ids = archive_result.get("released-event-ids") or None
    docs_result = render_release_docs(project_root, release_id, released_event_ids=released_ids)
    return {**archive_result, **docs_result}


def ensure_baseline(project_root: Path, branch: str = "main", python_version: str = "3.13") -> dict[str, Any]:
    """Ensure the release-please baseline workflow is in place."""
    return _rp_manage.ensure_baseline(project_root, branch, python_version)


def dispatch_release_workflow(
    owner: str | None = None,
    repo: str | None = None,
    release_id: str = "rel_0003",
    ref: str = "main",
    interactive: bool = True,
) -> dict[str, Any]:
    """Trigger the Release workflow dispatch on GitHub.

    POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches
    with inputs: release_id, ref.

    If no token is stored and interactive=True, opens browser for GitHub OAuth.
    """
    if owner is None or repo is None:
        parts = GITHUB_REPO.split("/")
        owner = parts[0]
        repo = parts[1] if len(parts) > 1 else GITHUB_REPO

    token = _load_token()
    if not token:
        if not interactive:
            raise AudiaGenticError(
                code="VAL-RELEASE-004",
                kind="release",
                message="No GitHub token stored and interactive auth disabled",
                details={"owner": owner, "repo": repo},
            )
        token = github_authenticate(interactive=True)

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{_RELEASE_WORKFLOW_ID}/dispatches"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    payload = {
        "ref": ref,
        "inputs": {"release_id": release_id},
    }
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(req) as resp:
            return {"dispatched": True, "url": url, "release_id": release_id, "status": resp.status}
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise AudiaGenticError(
            code="INT-RELEASE-002",
            kind="release",
            message=f"workflow dispatch failed: {e.code} {body}",
            details={"url": url, "response": body},
        )


def github_auth(interactive: bool = True) -> dict[str, Any]:
    """Return current GitHub auth status, or start the device flow.

    Non-blocking. If already authenticated (env/stored token), returns status.
    Otherwise, when ``interactive=True``, starts the OAuth device flow and
    returns the ``user_code``/``verification_uri`` for the caller to relay to
    the user, plus the ``device_code`` to pass to :func:`github_auth_poll`.
    """
    status = github_auth_status()
    if status.get("authenticated"):
        return status

    if not interactive:
        raise AudiaGenticError(
            code="VAL-RELEASE-007",
            kind="release",
            message="No GitHub token stored and interactive auth disabled",
        )

    flow = _start_device_flow(open_browser=True)
    return {
        "authenticated": False,
        "action-required": "authorize",
        "user-code": flow["user_code"],
        "verification-uri": flow["verification_uri"],
        "device-code": flow["device_code"],
        "interval": flow["interval"],
        "expires-in": flow["expires_in"],
        "instructions": (
            f"Open {flow['verification_uri']} and enter code {flow['user_code']}, "
            "then call github_auth_poll with the returned device-code."
        ),
    }


def github_auth_poll(device_code: str) -> dict[str, Any]:
    """Poll once for completion of a device flow started by :func:`github_auth`.

    Returns ``{"status": "pending"}`` while waiting, ``{"status": "slow_down"}``
    to back off, or the authenticated status once the token is granted.
    """
    result = _poll_device_flow(device_code)
    if result["status"] == "authorized":
        return github_auth_status()
    return result


def clear_github_auth() -> dict[str, Any]:
    """Remove stored GitHub token."""
    _clear_token()
    return {"cleared": True}
