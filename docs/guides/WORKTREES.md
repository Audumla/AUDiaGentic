# Task worktrees

One task is one branch in its own git worktree, merged by one squash pull request.
`audiagentic worktree` does the git bookkeeping so several sessions can work at the
same time without sharing state or leaving a mess behind. It works in any git
repository; the pull-request proof needs the `gh` CLI signed in to GitHub.

```
audiagentic worktree start SLUG [item ID] [purpose TEXT] [owner NAME] [project PATH]
audiagentic worktree list   [project PATH] [output json]
audiagentic worktree prune  [project PATH] [output json]
audiagentic worktree sync   [TARGET] [head TIP12] [dry-run yes] [project PATH] [output json]
audiagentic worktree push   [TARGET] [head TIP12] [dry-run yes] [project PATH] [output json]
audiagentic worktree merge  [TARGET] [title TEXT] [body TEXT] [head TIP12] [dry-run yes] [project PATH] [output json]
audiagentic worktree finish TARGET [abandon TIP12] [discard-ignored N] [project PATH] [output json]
```

Arguments are keywords (no `--` options). `audiagentic worktree help` prints the same text.

## The life of a worktree

1. **start** fetches the remote default branch (and stops if it cannot, so a stale base is
   never used), creates branch `OWNER/SLUG` and its worktree in one git step under a
   lock, and records the owner centrally. It prints the worktree's absolute path. That path
   is the `worktree` argument of the planning, ledger and gateway MCP tools, so a session
   started anywhere works on this checkout. A failed start is rolled back completely.
2. Work and commit in that directory. Push the branch and open the pull request as usual.
3. **list** shows every worktree: branch, uncommitted and untracked counts, commits ahead
   of and behind the default branch, owner, whether a process uses it, and whether the
   project marks it protected. A fact that cannot be established is shown as unknown.
4. **prune** is read-only. For each worktree it says `eligible`, `blocked` or `unknown`
   and names every blocker. It never fetches, writes or deletes.
5. **finish** removes exactly one worktree (below).

## Keeping a branch current: sync

`sync` is local only; it pushes nothing. It fetches the default branch and your branch, then
fast-forwards to the remote copy of the branch when that is strictly ahead (for example after
GitHub updated a pull request's branch), and merges the default branch in when the branch is
behind it. It never rebases, resets or forces, and it refuses on a dirty tree, a merge already
under way, unfinished gateway work, an unconfirmed `head`, and a remote branch that has diverged
from yours. A merge conflict is aborted and the worktree is left exactly as it was, with the
conflicting files listed. After a sync, publish the new tip with `merge` or `push`. This is the
fix for a pull request GitHub shows as "behind": the strict up-to-date rule needs the branch
to contain the default branch before auto-merge can finish.

## Publishing: push and merge

`push` publishes the worktree's tip. It runs the checks the project names, then pushes
exactly the checked commit as `refs/heads/BRANCH` without force, reads the remote back to
confirm it, and writes a receipt under the user state directory (`worktrees/receipts/`).
It refuses, and sends nothing, when the tree is dirty or the tip is not the `head TIP12`
you confirmed, when `origin` is not the repository the forge reports (or fetches from one
repository and pushes to another), when you cannot push, when gateway work in the worktree
is unfinished, when a check fails, and when anything changed while the checks ran. A remote
branch that has moved on is never overwritten: reconcile it yourself and push again.

Checks are trusted local code, so they are defined only in your own user settings. The
project names which ones must pass, by id:

```yaml
# project  .audiagentic/settings.yaml  (committed)
worktrees:
  pre-push: [privacy]
```
```yaml
# yours, in the user settings file (audiagentic config paths shows where)
worktrees:
  checks:
    privacy: [python3, tools/privacy_guard.py, --base, "{base}"]
```

A command is a fixed argument list (no shell). `{tip}`, `{base}` (the merge base with the
remote default branch) and `{worktree}` are replaced by the tool; the check runs in the
worktree with a minimal environment (no tokens). A project file that defines or changes
`worktrees.checks` is refused. `dry-run yes` lists the checks and the push without running
or sending anything.

`merge` publishes the worktree for merge and returns without waiting. It plans first (the
same report as `dry-run yes`), pushes the tip with the same checks as `push` unless the remote
already has that commit, opens the pull request (`title TEXT`, a conventional-commit title, is
required for a new one) or reuses the one open pull request for the branch, confirms the pull
request's head is the pushed commit, and asks GitHub to squash-merge it when the required
checks pass. The forge itself enforces the head commit (`--match-head-commit`), so a push made
after the check cannot be authorized, and every forge call is pinned to this repository. The
body is `body TEXT` followed by the project's `worktrees.pr-trailer`, if set.

It never waits for CI, never updates a branch that is behind (it reports `behind`; GitHub's
strict "up to date" rule then needs the branch updated before auto-merge can finish), never
replaces a closed pull request, and refuses an ambiguous or draft one. Run it again after any
failure: a tip already pushed is not pushed twice, an open pull request is reused, auto-merge
already on is left alone, and a tip whose pull request has merged reports "already merged".
GitHub merges at once if nothing is required of the pull request, so keep the required checks
in the repository's rules; they, not this command, are what make it wait.

## What counts as merged

Squash merges leave the branch tip unreachable from the default branch, so reachability
proves nothing. A worktree is merged only when all of this holds:

- a pull request on this repository has this branch as its head and its head commit equals
  the local tip (a fork's pull request does not count),
- its state is `MERGED` and it merged into the default branch,
- its merge commit is in the local default branch (`finish` fetches first; `prune` does not,
  so it reports `merge-commit-not-fetched` when the local copy is stale).

Anything else is `blocked`; anything the tools cannot find out (the forge is unreachable,
`/proc` is unavailable, the gateway's records are unreadable, two pull requests share the
tip) is `unknown`, and unknown refuses exactly like blocked.

## What always blocks

A primary or protected worktree, a git lock, a detached HEAD, uncommitted or untracked
files, initialized submodules, ignored files that are not caches or project records, any
process using the directory, and unfinished gateway requests or sessions in it.
Disposable caches (`__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`) are
allowed. Run `prune` to see the exact reasons.

## finish

`finish TARGET` takes the absolute path, or a branch or directory name when that is
unique. It:

1. fetches the default branch, then takes a per-project lock and fences the worktree so
   MCP calls cannot start new work in it,
2. runs the `prune` checks and records what it saw,
3. preserves first: an immutable `refs/quarantine/...` ref at the tip, and a verified copy
   of the project's ignored record files (everything ignored under `.audiagentic/`) in the
   central archive,
4. runs the checks again and refuses if anything differs (branch, tip, pull request,
   worktree identity, ignored files, record contents),
5. removes the worktree with plain `git worktree remove` (never `--force`), deletes the
   branch only if it still points at the recorded tip, and forgets the owner record,
6. moves the task's scratch directory `<dev-root>/tmp/<project>/<branch>/` (the branch name
   with its owner prefix) to `<dev-root>/tmp/<project>/.finished/`. Nothing is deleted: the
   container's scratch sweep removes it later, so agents never need a recursive delete. A
   missing directory, a link, or a name that is not plain path segments is left alone.

Ignored files that are not caches or records refuse until you repeat the count the refusal
printed: `discard-ignored 3`. A crash resumes from a journal on the next `finish`; a
refusal before removal leaves everything as it was.

### Unmerged work

`finish` refuses unmerged work and prints `abandon TIP12`, the first twelve characters
of the tip you would discard. Repeating that token abandons the work. Only the merged-pull-
request proof is waived; every other check still applies, and uncommitted changes still
refuse (commit them first). Before removal the full history of the tip is written to a
self-contained, verified `git bundle` with its checksum.

## Where things are kept

Nothing is written into the worktree. State lives in the user state directory, under
`worktrees/`: owner records, the removal journals (one per attempt, earlier ones are kept),
the archive (record copies and bundles) and the fences. Quarantine refs live in the
repository itself. To restore abandoned work:

```
git fetch ARCHIVE/....bundle refs/quarantine/KEY/TX:refs/heads/restored
```

`git for-each-ref refs/quarantine` lists them. They are never deleted by these commands.

## Settings

In `.audiagentic/settings.yaml` (see [PROJECT_SETTINGS](PROJECT_SETTINGS.md)):

| Key | Default | Meaning |
|---|---|---|
| `worktrees.root` | `<main worktree>.worktrees` beside the main worktree | where `start` creates worktrees |
| `worktrees.branch-prefix` | `{owner}/` | prefix of new branch names |
| `worktrees.protected` | none | name to path map of worktrees that are never removed |
| `worktrees.pre-push` | none | ids of the checks `push` and `merge` must pass before publishing (the union of your list and the project's) |
| `worktrees.checks` | none | **user settings only**: id to a fixed command list (`{tip}`, `{base}`, `{worktree}`) |
| `worktrees.pr-trailer` | none | text appended to the body of pull requests `merge` opens |

`audiagentic doctor` reports a primary checkout that is off the default branch, behind it
or diverged. It reports only; it never changes anything.

## Limits

- A process that ignores the fence can still write into a worktree between the final check
  and the removal. The checks reduce that window; they cannot close it.
- The archive has no size limit; a full disk refuses before anything is removed.
- The bundle covers the abandoned tip only. Other local branches and stashes are neither
  backed up nor removed.
- Only GitHub through `gh` is supported as a forge.
- Checks run in the live worktree and are trusted code; another writer can still advance the
  remote branch after the final check (a non-force push cannot overwrite it).
