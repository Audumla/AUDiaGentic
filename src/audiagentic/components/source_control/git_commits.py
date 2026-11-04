"""Post-commit hook: stamp ledger events with git commit SHAs.

For each unreleased ledger event whose file list intersects the committed
files, appends the commit SHA to that event's git-commits list. An event can
accumulate multiple SHAs if its files were committed in stages — this is
correct.

Only the tracked files of events this commit introduced are annotated; the
frozen baseline, the historical ledger, every shared file and every event file
added by an earlier commit are never rewritten.

Called from post_commit_ledger_hook.sh, not from Python. That shell-only entry
point is why an importer scan reports this module as unreferenced; it is not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from audiagentic.components.ledger.current_events import event_files_in_tree, event_text
from audiagentic.foundation.io import atomic_write_text


def _get_head_sha(project_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _events_added_by_head(project_root: Path) -> set[str]:
    """Names of event files this commit introduced (a stamp never rewrites an older, already shared event file)."""
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "--diff-filter=A", "-r", "HEAD"],
        cwd=project_root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    return {Path(line.strip()).name for line in result.stdout.splitlines() if line.strip().endswith(".json")}


def _get_committed_files(project_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "show", "HEAD", "--name-only", "--format="],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def stamp_ledger_for_commit(project_root: Path) -> dict[str, list[str]]:
    """Stamp current-ledger events whose files intersect the HEAD commit.

    Returns a dict mapping commit SHA to the list of stamped event-ids.
    No-ops cleanly if git is unavailable or the ledger does not exist.
    """
    # Enforce the policy at execution time as well as installation time. A
    # stale or manually retained hook must not re-enter the release ledger.
    from audiagentic.components.source_control.source_control_bootstrap import (
        post_commit_ledger_stamp_enabled,
    )
    if not post_commit_ledger_stamp_enabled(project_root):
        return {}

    sha = _get_head_sha(project_root)
    if not sha:
        return {}

    committed_files = _get_committed_files(project_root)
    if not committed_files:
        return {}

    # Annotate only the events' own files: the frozen baseline and any shared file are never rewritten.
    stamped: list[str] = []
    introduced = _events_added_by_head(project_root)
    for path, event in event_files_in_tree(project_root):
        if path.name not in introduced or not set(event.get("files") or []).intersection(committed_files):
            continue
        commits: list[str] = list(event.get("git-commits") or [])
        if sha in commits:
            continue
        commits.append(sha)
        atomic_write_text(path, event_text({**event, "git-commits": commits}))
        stamped.append(event["event-id"])

    return {sha: stamped} if stamped else {}
