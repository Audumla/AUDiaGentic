# Task worktrees

One task is one branch in its own git worktree, merged by one squash pull request.
`audiagentic worktree` does the git bookkeeping so several sessions can work at the
same time without sharing state or leaving a mess behind. It works in any git
repository; the pull-request proof needs the `gh` CLI signed in to GitHub.

```
audiagentic worktree start SLUG [item ID] [purpose TEXT] [owner NAME] [project PATH]
audiagentic worktree list   [project PATH] [output json]
audiagentic worktree prune  [project PATH] [output json]
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
   branch only if it still points at the recorded tip, and forgets the owner record.

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

`audiagentic doctor` reports a primary checkout that is off the default branch, behind it
or diverged. It reports only; it never changes anything.

## Limits

- A process that ignores the fence can still write into a worktree between the final check
  and the removal. The checks reduce that window; they cannot close it.
- The archive has no size limit; a full disk refuses before anything is removed.
- The bundle covers the abandoned tip only. Other local branches and stashes are neither
  backed up nor removed.
- Only GitHub through `gh` is supported as a forge. There is no `worktree merge` yet.
