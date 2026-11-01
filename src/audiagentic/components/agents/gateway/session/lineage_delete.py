"""The one gateway-local session-lineage deletion (SH32-B), shared by manual and policy purge.

It deletes request directories and archives, the session's binding entry and relocated-root
registration, and the session directory LAST (the parent record carries the retention claim and the
recorded plan, so a crash before the parent goes leaves everything needed to resume). Callers hold
the maintenance and retention locks. ``strict=False`` keeps the manual purge's best-effort removal;
``strict=True`` (policy purge) lets a failed removal raise so the claim is kept and the operation can
be replayed. Every step is idempotent. Gateway-local files only: never a remote provider conversation.
"""
from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def _remove(path: Path, *, strict: bool) -> None:
    if not path.exists():
        return
    shutil.rmtree(path, ignore_errors=not strict)
    if strict and path.exists():
        raise OSError(f"could not remove {path.name}")


def delete_session_lineage(
    project_root: Path, session_id: str, request_ids: Iterable[str], record: dict[str, Any], *, strict: bool,
) -> None:
    from audiagentic.components.agents.agents_paths import (
        gateway_request_dir,
        gateway_root,
        gateway_session_dir,
    )
    from audiagentic.components.agents.gateway.session import bindings as binding_store
    from audiagentic.components.agents.gateway.session import root_registry

    root = gateway_root(project_root)
    for request_id in sorted(set(request_ids)):
        _remove(gateway_request_dir(project_root, request_id), strict=strict)
        _remove(root / "archive" / request_id, strict=strict)
    binding_store.purge_binding(project_root, record)
    root_registry.unregister_session_root(project_root, session_id=session_id)
    _remove(gateway_session_dir(project_root, session_id), strict=strict)
