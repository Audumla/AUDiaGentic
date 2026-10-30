"""Per-call git worktree selection shared by every worktree-scoped MCP server.

One session works in several git worktrees, so a server cannot bind one
project at start-up. A worktree-scoped server (declared ``worktree-scoped:
true`` in its component YAML) gives every tool an optional ``worktree`` argument:
the absolute path of the git worktree to act on. It must be the ROOT of a
git worktree (plans, ledger events and gateway state are files that belong
to a branch). When omitted, the server's own project is used (an explicit
``AUDIAGENTIC_REPO_ROOT``, else the git checkout the server runs in), and it
must itself be a git worktree root. Anything that cannot be confirmed is a clear
error, never a guess. The chosen worktree applies to that call only:
``project_root_from_env()`` returns it, so tools need no code of their own,
and every result reports it so the caller can confirm the right one was used.
"""
from __future__ import annotations

import contextvars
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.paths.project import describe_checkout, discover_checkout_root
from audiagentic.foundation.system import worktree_drain

worktree_error = make_error_factory("CFG", "MCPWT", "mcp")

WORKTREE_PARAMETER = "worktree"
WORKTREE_DESCRIPTION = (
    "Absolute path of the git worktree to act on (the worktree root, not a subdirectory). "
    "Omit to use this server's own project. The result reports the worktree used."
)

_CURRENT: contextvars.ContextVar[Worktree | None] = contextvars.ContextVar("audiagentic_mcp_worktree", default=None)


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str | None
    head: str | None

    def to_dict(self) -> dict[str, str | None]:
        return {"path": str(self.path), "branch": self.branch, "head": self.head}


def _confirm(candidate: Path) -> Worktree:
    if not candidate.is_dir():
        raise worktree_error(3, "Worktree path does not exist or is not a directory", worktree=str(candidate))
    resolved = candidate.resolve()
    root = discover_checkout_root(resolved)
    if root is None:
        raise worktree_error(4, "Path is not inside a git worktree", worktree=str(resolved))
    if root != resolved:
        raise worktree_error(
            # The root is the fix, so it goes in the message: error details are
            # truncated for clients, which would cut a long path.
            5, f"Path is inside a git worktree but is not its root; use {root}",
            worktree=str(resolved), worktree_root=str(root),
        )
    if worktree_drain.is_draining(resolved):
        raise worktree_error(
            6, "This worktree is being removed and accepts no new work",
            worktree=str(resolved), reason=worktree_drain.reason(resolved),
        )
    branch, head = describe_checkout(resolved)
    return Worktree(resolved, branch, head)


def resolve_worktree(requested: str | None) -> Worktree:
    """The worktree for one call: the requested path, else the server's own project."""
    if requested is not None and str(requested).strip():
        path = Path(str(requested).strip()).expanduser()
        if not path.is_absolute():
            raise worktree_error(2, "Worktree must be an absolute path", worktree=str(requested))
        return _confirm(path)
    # The server's own project: an explicit root, else the git checkout it runs
    # in. No marker walk-up: an unrelated ancestor must never be guessed.
    explicit = os.environ.get("AUDIAGENTIC_REPO_ROOT", "").strip()
    default = Path(explicit) if explicit else discover_checkout_root(Path.cwd())
    if default is None:
        raise worktree_error(
            1, "No worktree was given and this server is not running in a git worktree",
            server_cwd=os.getcwd(), parameter=WORKTREE_PARAMETER,
        )
    return _confirm(Path(default))


def current_worktree() -> Worktree | None:
    """The worktree selected for the tool call in progress, if any."""
    return _CURRENT.get()


@contextmanager
def using_worktree(worktree: Worktree) -> Iterator[Worktree]:
    token = _CURRENT.set(worktree)
    try:
        yield worktree
    finally:
        _CURRENT.reset(token)


__all__ = [
    "WORKTREE_DESCRIPTION",
    "WORKTREE_PARAMETER",
    "Worktree",
    "current_worktree",
    "resolve_worktree",
    "using_worktree",
    "worktree_error",
]
