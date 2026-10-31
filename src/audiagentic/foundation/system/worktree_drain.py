"""Per-worktree drain markers (DW01): the fence a removal puts in front of new work.

A removal in progress writes a marker for the worktree's canonical path in the user
state directory. Every MCP call resolves its worktree through
``foundation.mcp.worktree.resolve_worktree``, which refuses a draining worktree, so
no planning, ledger or gateway call can start new work there while it is being
removed. The marker is a fence for callers that resolve through that path; it does
not stop a process that already holds the directory (the removal's process and
active-work checks cover those) or a caller that bypasses the resolver.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.time import now_iso_z


def _marker(path: Path, state_root: Path | None) -> Path:
    key = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:24]
    return (state_root or user_state_dir()) / "worktrees" / "draining" / f"{key}.json"


def begin(path: Path, *, reason: str, state_root: Path | None = None) -> None:
    """Fence ``path``. Idempotent."""
    marker = _marker(path, state_root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(marker, {"path": str(path.resolve()), "reason": reason, "since": now_iso_z()})


def end(path: Path, *, state_root: Path | None = None) -> None:
    """Lift the fence. Idempotent."""
    _marker(path, state_root).unlink(missing_ok=True)


def is_draining(path: Path, *, state_root: Path | None = None) -> bool:
    return _marker(path, state_root).exists()


def reason(path: Path, *, state_root: Path | None = None) -> str | None:
    try:
        return json.loads(_marker(path, state_root).read_text(encoding="utf-8")).get("reason")
    except (OSError, ValueError):
        return None
