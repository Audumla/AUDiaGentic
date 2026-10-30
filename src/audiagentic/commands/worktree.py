"""Keyword CLI for the worktree lifecycle (DW01): protocol adapter only.

Grammar is closed and word-based, like the gateway commands; ``--`` options are
rejected. The project component owns the behaviour (``components/project/worktrees``).
"""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.cli_io import print_error, print_json, print_message

_HELP = """Worktree commands (keyword syntax):
  audiagentic worktree list [project PATH] [output json]
  audiagentic worktree start SLUG [item ID] [purpose TEXT] [owner NAME] [project PATH] [output json]
  audiagentic worktree prune [project PATH] [output json]
  audiagentic worktree help

start fetches the remote default branch (and refuses to continue if it cannot, so a
stale base is never used), then creates a new branch OWNER/SLUG and its own worktree
from it in one step, under a project lock, and records the owner centrally (nothing is
written into the worktree). It prints the worktree path: that absolute path is the
`worktree` argument of the planning, ledger and gateway MCP tools. A failed start is
rolled back completely. SLUG is 1-48 lowercase letters, digits or hyphens.

list shows every git worktree of the repository containing PATH (default: the
current directory): branch, uncommitted and untracked counts, commits ahead of and
behind the remote default branch, owner (when recorded), whether a process is using
it, and whether the project marks it protected. It is read-only. A fact that cannot
be established is shown as unknown, never guessed. Pull-request state is not shown
yet (it needs the forge adapter).

prune is read-only: it reports, for every worktree, whether it could be finished and
exactly what blocks it. Work counts as merged only with proof: a pull request on this
repository whose head equals the local tip, state MERGED into the default branch,
and whose merge commit is in the local default branch (run `git fetch` first when it
says the merge commit is not fetched). It also refuses on uncommitted or untracked
files, unknown ignored files, a process using the path, unfinished gateway work, a git
lock, submodules, a detached HEAD, a protected or primary worktree. Anything it cannot
establish is reported as unknown, which also blocks. prune never deletes anything.
Options beginning with -- are not accepted; use the keywords shown above."""


def dispatch_keyword(tokens: list[str]) -> int:
    """Closed keyword route; parse and help before importing any owner."""
    if not tokens or tokens in (["help"], ["list", "help"], ["start", "help"]):
        print_message(_HELP)
        return 0
    if tokens[0] not in {"list", "start", "prune"} or any(token.startswith("--") for token in tokens):
        print_error("Invalid worktree syntax. Run: audiagentic worktree help")
        return 2
    if tokens[0] == "start":
        return _start(tokens[1:])
    if tokens[0] == "prune":
        return _prune(tokens[1:])
    clauses = _clauses(tokens[1:], {"project", "output"})
    if clauses is None:
        print_error("Invalid worktree list syntax. Run: audiagentic worktree help")
        return 2

    from audiagentic.components.project.worktrees.service import list_rows
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.paths.project import discover_checkout_root

    start = Path(clauses["project"]).resolve() if "project" in clauses else None
    repo = discover_checkout_root(start)
    if repo is None:
        print_error("Not inside a git repository. Give project PATH or run it inside one.")
        return 2
    try:
        result = list_rows(repo)
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    if clauses.get("output") == "json":
        print_json(result, sort_keys=True)
    else:
        print_message(_table(result))
    return 0


def _clauses(rest: list[str], allowed: set[str]) -> dict[str, str] | None:
    """Keyword clauses, each at most once; a value consumes exactly one token."""
    clauses: dict[str, str] = {}
    while rest:
        key, *rest = rest
        if key not in allowed or key in clauses or not rest:
            return None
        clauses[key], *rest = rest
    return None if clauses.get("output", "json") != "json" else clauses


def _prune(tokens: list[str]) -> int:
    clauses = _clauses(tokens, {"project", "output"})
    if clauses is None:
        print_error("Invalid worktree prune syntax. Run: audiagentic worktree help")
        return 2

    from audiagentic.components.agents.gateway.api import worktree_active_work
    from audiagentic.components.project.worktrees.eligibility import assess_all
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.paths.project import discover_checkout_root

    repo = discover_checkout_root(Path(clauses["project"]).resolve() if "project" in clauses else None)
    if repo is None:
        print_error("Not inside a git repository. Give project PATH or run it inside one.")
        return 2
    try:
        result = assess_all(repo, active_work=worktree_active_work)
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    if clauses.get("output") == "json":
        print_json(result, sort_keys=True)
        return 0
    lines = [f"default branch: {result['default-branch'] or 'unknown'}"]
    for row in result["worktrees"]:
        lines.append(f"{row['verdict'].upper():8} {row['path']}  [{row['branch'] or 'detached'}]")
        lines.extend(f"    {'?' if b['unknown'] else '-'} {b['code']}: {b['detail']}" for b in row["blockers"])
        lines.extend(f"    note: {note}" for note in row["notes"])
    print_message("\n".join(lines))
    return 0


def _start(tokens: list[str]) -> int:
    if not tokens:
        print_error("worktree start needs a SLUG. Run: audiagentic worktree help")
        return 2
    slug, *rest = tokens
    clauses = _clauses(rest, {"item", "purpose", "owner", "project", "output"})
    if clauses is None:
        print_error("Invalid worktree start syntax. Run: audiagentic worktree help")
        return 2

    from audiagentic.components.project.worktrees import lifecycle
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.paths.project import discover_checkout_root

    repo = discover_checkout_root(Path(clauses["project"]).resolve() if "project" in clauses else None)
    if repo is None:
        print_error("Not inside a git repository. Give project PATH or run it inside one.")
        return 2
    try:
        started = lifecycle.start(
            repo, slug, plan_item=clauses.get("item"), purpose=clauses.get("purpose", ""),
            owner={"account": clauses["owner"]} if "owner" in clauses else None)
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    result = {"worktree-id": started.worktree_id, "path": str(started.path), "branch": started.branch,
              "base": started.base, "base-head": started.base_head}
    if clauses.get("output") == "json":
        print_json(result, sort_keys=True)
    else:
        print_message(f"{started.path}\nbranch {started.branch} from {started.base} ({(started.base_head or '?')[:9]})")
    return 0


def _table(result: dict) -> str:
    lines = [f"default branch: {result['default-branch'] or 'unknown'}"]
    for row in result["worktrees"]:
        flags = [name for name, on in (("primary", row["primary"]), ("protected", row["protected"]),
                                       ("locked", row["locked"]), ("prunable", row["prunable"]),
                                       ("detached", row["detached"])) if on]
        relation = ("base unknown" if row["ahead"] is None
                    else f"+{row['ahead']}/-{row['behind']} vs base")
        users = "processes unknown" if row["processes"] is None else f"{len(row['processes'])} process(es)"
        owner = (row["owner"] or {}).get("session") or "unowned"
        lines.append(f"{row['path']}  [{row['branch'] or 'detached'}]  {relation}  "
                     f"{row['changes']} changed, {row['untracked']} untracked  {users}  {owner}"
                     + (f"  ({', '.join(flags)})" if flags else ""))
    for orphan in result["orphan-records"]:
        lines.append(f"orphan record {orphan['worktree-id']}: {orphan['path']} is no longer a git worktree")
    return "\n".join(lines)
