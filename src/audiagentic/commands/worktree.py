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
  audiagentic worktree sync [TARGET] [head TIP12] [dry-run yes] [project PATH] [output json]
  audiagentic worktree push [TARGET] [head TIP12] [dry-run yes] [project PATH] [output json]
  audiagentic worktree ship [TARGET] [title TEXT] [body TEXT] [head TIP12] [project PATH] [output json]
  audiagentic worktree merge [TARGET] [title TEXT] [body TEXT] [head TIP12] [dry-run yes] [project PATH] [output json]
  audiagentic worktree tidy [apply yes] [project PATH] [output json]
  audiagentic worktree finish TARGET [abandon TIP] [discard-ignored N] [project PATH] [output json]
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
repository whose head equals (or contains) the local tip, state MERGED into the default branch,
and whose merge commit is in the local default branch (run `git fetch` first when it
says the merge commit is not fetched). It also refuses on uncommitted or untracked
files, unknown ignored files, a process using the path, unfinished gateway work, a git
lock, submodules, a detached HEAD, a protected or primary worktree. Anything it cannot
establish is reported as unknown, which also blocks. prune never deletes anything.

sync brings a task branch up to date, locally only (nothing is pushed): it fetches the default
branch and this branch, fast-forwards to the remote copy when that is strictly ahead (for example after
the forge updated a pull request's branch), and merges the default branch in when the branch is behind
it. It never rebases or resets, and refuses on a dirty tree, a merge already under way, unfinished
gateway work, a diverged remote branch, and a conflict (the merge is aborted and nothing changes).
Publish the new tip afterwards with merge or push. `dry-run yes` fetches nothing and changes nothing.

push runs the pre-push checks your project names (worktrees.pre-push, the ids) with the commands
you define in your own user settings (worktrees.checks: id to a fixed command list; a project file
cannot define them), then pushes exactly the checked commit as refs/heads/BRANCH without force,
reads the remote back to confirm, and writes a receipt. It refuses when the tree is dirty, the
remote is not the repository the forge reports, you cannot push, or gateway work is unfinished,
and again if anything changed while the checks ran. `dry-run yes` lists the checks and the push
without running or sending anything. TARGET defaults to the worktree you are in.

ship is the everyday command: it runs sync, then merge, in that order, and returns without waiting. Run it
again whenever the default branch moved (for example a release landed) and the pull request shows BEHIND: it
syncs, pushes the new tip and keeps auto-merge on. When the pull request has merged it says so and names
the finish command. It has no options of its own beyond the title, body and head of merge.

merge publishes a worktree for merge and returns without waiting: it plans (every check of
`dry-run yes`), pushes the tip with the same checks as `push` unless the remote already has it,
opens the pull request (title TEXT must be a conventional-commit title) or reuses the one open
pull request for the branch, confirms its head is the pushed commit, and asks the forge to
squash-merge it when the required checks pass. It never updates a branch that is behind, never
replaces a closed pull request, never waits for CI. Run it again after any failure: each step
converges. `dry-run yes` only reports what it would do and what blocks it. TARGET defaults to the
worktree you are in. The body is `body TEXT` plus the project's worktrees.pr-trailer, if set.

tidy reports (and, with `apply yes`, does) the routine cleanup: it drops records whose directory is gone and
git no longer lists, and finishes every worktree that prune marks ELIGIBLE (merge proven, clean, unused),
one at a time through the same finish. Anything else is listed with its blockers and left alone.

finish removes exactly one worktree whose work is merged (TARGET is its absolute path, or
its branch or directory name when that is unique). It fetches the default branch, fences
new work, runs the same checks as prune twice and compares them, writes an immutable
refs/quarantine/ ref at the tip and a verified archive copy of the project's ignored
record files, then removes the worktree with plain non-force git and deletes the branch
only if it still points at the recorded tip. Ignored files that are not caches or records
refuse unless you repeat the count the refusal printed as `discard-ignored N`. A crash
resumes from a journal; a refusal before removal leaves everything untouched. Unmerged
work is refused unless you repeat the tip the refusal printed as `abandon TIP`: its full
history is then written to a self-contained git bundle, verified and checksummed in the central archive before the worktree is removed. Uncommitted changes
still refuse; commit them first.
Options beginning with -- are not accepted; use the keywords shown above."""


def dispatch_keyword(tokens: list[str]) -> int:
    """Closed keyword route; parse and help before importing any owner."""
    if not tokens or tokens in (["help"], ["list", "help"], ["start", "help"]):
        print_message(_HELP)
        return 0
    if tokens[0] not in {"list", "start", "prune", "finish", "merge", "push", "sync", "ship", "tidy"} or any(token.startswith("--") for token in tokens):
        print_error("Invalid worktree syntax. Run: audiagentic worktree help")
        return 2
    if tokens[0] == "start":
        return _start(tokens[1:])
    if tokens[0] == "prune":
        return _prune(tokens[1:])
    if tokens[0] == "finish":
        return _finish(tokens[1:])
    if tokens[0] == "tidy":
        return _tidy(tokens[1:])
    if tokens[0] == "ship":
        return _ship(tokens[1:])
    if tokens[0] == "merge":
        return _merge(tokens[1:])
    if tokens[0] == "push":
        return _push(tokens[1:])
    if tokens[0] == "sync":
        return _sync(tokens[1:])
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


def _sync(tokens: list[str]) -> int:
    target = tokens[0] if tokens and tokens[0] not in {"head", "dry-run", "project", "output"} else None
    clauses = _clauses(tokens[1:] if target else tokens, {"head", "dry-run", "project", "output"})
    if clauses is None or clauses.get("dry-run", "yes") != "yes":
        print_error("Invalid worktree sync syntax. Run: audiagentic worktree help")
        return 2

    from audiagentic.components.agents.gateway.api import worktree_active_work
    from audiagentic.components.project.worktrees import sync as syncer
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.paths.project import discover_checkout_root

    here = discover_checkout_root(Path(clauses["project"]).resolve() if "project" in clauses else None)
    if here is None:
        print_error("Not inside a git repository. Give project PATH or run it inside one.")
        return 2
    path = Path(target).expanduser().resolve() if target and "/" in target else here
    try:
        result = syncer.sync(here, path, head=clauses.get("head"), active_work=worktree_active_work,
                             dry_run="dry-run" in clauses)
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    if clauses.get("output") == "json":
        print_json(result, sort_keys=True)
    elif not result["actions"]:
        print_message(f"{result['branch']} is up to date ({result['before'][:12]})")
    else:
        verb = "would (offline estimate from the last fetch)" if result["dry-run"] else "did"
        lines = [f"{verb}: {action}" for action in result["actions"]]
        lines.append(f"{result['before'][:12]} -> {result['after'][:12]}" if not result["dry-run"] else "nothing was changed")
        lines += [result["next"]] if result["next"] else []
        print_message("\n".join(lines))
    return 0


def _push(tokens: list[str]) -> int:
    target = tokens[0] if tokens and tokens[0] not in {"head", "dry-run", "project", "output"} else None
    clauses = _clauses(tokens[1:] if target else tokens, {"head", "dry-run", "project", "output"})
    if clauses is None or clauses.get("dry-run", "yes") != "yes":
        print_error("Invalid worktree push syntax. Run: audiagentic worktree help")
        return 2

    from audiagentic.components.agents.gateway.api import worktree_active_work
    from audiagentic.components.project.worktrees import publish
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.paths.project import discover_checkout_root

    here = discover_checkout_root(Path(clauses["project"]).resolve() if "project" in clauses else None)
    if here is None:
        print_error("Not inside a git repository. Give project PATH or run it inside one.")
        return 2
    path = Path(target).expanduser().resolve() if target and "/" in target else here
    try:
        result = publish.push(here, path, head=clauses.get("head"), active_work=worktree_active_work,
                              dry_run="dry-run" in clauses)
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    if clauses.get("output") == "json":
        print_json(result, sort_keys=True)
    elif result["dry-run"]:
        print_message(f"{result['would']}\nchecks: {', '.join(result['checks']) or 'none required'}")
    else:
        print_message(f"pushed {result['tip'][:12]} to origin/{result['branch']} (confirmed on the remote); "
                      f"{len(result['checks'])} check(s) passed")
    return 0


def _ship(tokens: list[str]) -> int:
    words = {"title", "body", "head", "project", "output"}
    target = tokens[0] if tokens and tokens[0] not in words else None
    clauses = _clauses(tokens[1:] if target else tokens, words)
    if clauses is None:
        print_error("Invalid worktree ship syntax. Run: audiagentic worktree help")
        return 2

    from audiagentic.components.agents.gateway.api import worktree_active_work
    from audiagentic.components.project.worktrees import ship as shipper
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.paths.project import discover_checkout_root

    here = discover_checkout_root(Path(clauses["project"]).resolve() if "project" in clauses else None)
    if here is None:
        print_error("Not inside a git repository. Give project PATH or run it inside one.")
        return 2
    path = Path(target).expanduser().resolve() if target and "/" in target else here
    try:
        result = shipper.ship(here, path, title=clauses.get("title"), body=clauses.get("body"),
                              head=clauses.get("head"), active_work=worktree_active_work)
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    if clauses.get("output") == "json":
        print_json(result, sort_keys=True)
        return 0
    lines = []
    if result["synced"]:
        lines += [f"synced: {action}" for action in result["synced"]]
    if result["state"] == "merged":
        lines.append(f"merged: #{result['pr']} {result['url']}")
    else:
        lines.append(f"{'pushed ' + result['tip'][:12] if result['pushed'] else 'already on the remote'}; "
                     f"#{result['pr']} {result['url']} is {result['state']} ({result['merge-state'] or 'pending'})")
    lines.append(f"next: {result['next']}")
    print_message("\n".join(lines))
    return 0


def _merge(tokens: list[str]) -> int:
    words = {"title", "body", "head", "dry-run", "project", "output"}
    target = tokens[0] if tokens and tokens[0] not in words else None
    clauses = _clauses(tokens[1:] if target else tokens, words)
    if clauses is None or clauses.get("dry-run", "yes") != "yes":
        print_error("Invalid worktree merge syntax. Run: audiagentic worktree help")
        return 2

    from audiagentic.components.agents.gateway.api import worktree_active_work
    from audiagentic.components.project.worktrees import merge as merger
    from audiagentic.components.project.worktrees import merge_plan
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.paths.project import discover_checkout_root

    start = Path(clauses["project"]).resolve() if "project" in clauses else None
    here = discover_checkout_root(start)
    if here is None:
        print_error("Not inside a git repository. Give project PATH or run it inside one.")
        return 2
    path = Path(target).expanduser().resolve() if target and "/" in target else here
    dry_run = "dry-run" in clauses
    try:
        if dry_run:
            result = merge_plan.plan(here, path, title=clauses.get("title"), head=clauses.get("head"),
                                     active_work=worktree_active_work)
        else:
            result = merger.merge(here, path, title=clauses.get("title"), body=clauses.get("body"),
                                  head=clauses.get("head"), active_work=worktree_active_work)
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    if clauses.get("output") == "json":
        print_json(result, sort_keys=True)
        return 0
    if not dry_run and result.get("already-merged"):
        print_message(f"already merged: a pull request with this exact tip ({result['tip'][:12]}) is merged; nothing to do")
        return 0
    if not dry_run:
        state = "BEHIND the default branch: run worktree sync" if result["behind"] else (result["merge-state"] or "pending")
        print_message(f"{'opened' if result['created'] else 'reused'} #{result['pr']} {result['url']}\n"
                      f"{'pushed ' + result['tip'][:12] if result['pushed'] else 'already on the remote'}; "
                      f"auto-merge on; state {state}")
        return 0
    lines = [f"{result['verdict'].upper()}  {result['worktree']}  [{result['branch'] or 'detached'}]  tip {result['tip'][:12]}"]
    lines += [f"  {'?' if b['unknown'] else '-'} {b['code']}: {b['detail']}" for b in result["blockers"]]
    lines += [f"  would: {op['action']} ({op['detail']})" for op in result["operations"]]
    print_message("\n".join(lines))
    return 0


def _tidy(tokens: list[str]) -> int:
    clauses = _clauses(tokens, {"apply", "project", "output"})
    if clauses is None or clauses.get("apply", "yes") != "yes":
        print_error("Invalid worktree tidy syntax. Run: audiagentic worktree help")
        return 2

    from audiagentic.components.agents.gateway.api import worktree_active_work
    from audiagentic.components.project.worktrees.tidy import tidy
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.paths.project import discover_checkout_root

    repo = discover_checkout_root(Path(clauses["project"]).resolve() if "project" in clauses else None)
    if repo is None:
        print_error("Not inside a git repository. Give project PATH or run it inside one.")
        return 2
    try:
        result = tidy(repo, active_work=worktree_active_work, apply="apply" in clauses)
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    print_json(result, sort_keys=True)
    return 0


def _finish(tokens: list[str]) -> int:
    if not tokens:
        print_error("worktree finish needs a TARGET. Run: audiagentic worktree help")
        return 2
    target, *rest = tokens
    clauses = _clauses(rest, {"discard-ignored", "abandon", "project", "output"})
    if clauses is None or not clauses.get("discard-ignored", "0").isdigit():
        print_error("Invalid worktree finish syntax. Run: audiagentic worktree help")
        return 2

    from audiagentic.components.agents.gateway.api import worktree_active_work
    from audiagentic.components.project.worktrees.finish import finish
    from audiagentic.foundation.contracts.errors import AudiaGenticError
    from audiagentic.foundation.paths.project import discover_checkout_root

    repo = discover_checkout_root(Path(clauses["project"]).resolve() if "project" in clauses else None)
    if repo is None:
        print_error("Not inside a git repository. Give project PATH or run it inside one.")
        return 2
    try:
        result = finish(repo, target, active_work=worktree_active_work,
                        discard_ignored=int(clauses["discard-ignored"]) if "discard-ignored" in clauses else None,
                        abandon=clauses.get("abandon"))
    except AudiaGenticError as error:
        print_error(f"{error.code}: {error.message}")
        return 1
    if clauses.get("output") == "json":
        print_json(result, sort_keys=True)
    else:
        lines = [f"finished {result['path']} (branch {result['branch']}, PR #{result['pr']})",
                 f"quarantine ref {result['quarantine-ref']}"]
        lines += [f"archive {result['archive']}"] if result["archive"] else []
        if result["bundle"]:
            lines.append(f"bundle {result['bundle']['path']} ({result['bundle']['commits']} commit(s), "
                         f"sha256 {result['bundle']['sha256'][:16]}...)")
        lines += [f"note: {note}" for note in result["notes"]]
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
