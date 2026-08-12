"""Post-commit hook: stamp ledger events with git commit SHAs.

For each unreleased ledger event whose file list intersects the committed
files, appends the commit SHA to that event's git-commits list. An event can
accumulate multiple SHAs if its files were committed in stages — this is
correct.

Only the current (unreleased) ledger is stamped; the historical ledger holds
released events, which must not be rewritten.

Called from post_commit_ledger_hook.sh, not from Python. That shell-only entry
point is why an importer scan reports this module as unreferenced; it is not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from audiagentic.components.ledger.paths import current_ledger_path
from audiagentic.foundation.io import atomic_write_ndjson, load_ndjson


def _get_head_sha(project_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


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
    sha = _get_head_sha(project_root)
    if not sha:
        return {}

    committed_files = _get_committed_files(project_root)
    if not committed_files:
        return {}

    ledger_path = current_ledger_path(project_root)
    if not ledger_path.exists():
        return {}

    entries = load_ndjson(ledger_path)
    if not entries:
        return {}

    stamped: list[str] = []
    for entry in entries:
        if not set(entry.get("files") or []).intersection(committed_files):
            continue
        commits: list[str] = list(entry.get("git-commits") or [])
        if sha in commits:
            continue
        commits.append(sha)
        entry["git-commits"] = commits
        stamped.append(entry.get("event-id"))

    if not stamped:
        return {}

    atomic_write_ndjson(ledger_path, entries)
    return {sha: stamped}
