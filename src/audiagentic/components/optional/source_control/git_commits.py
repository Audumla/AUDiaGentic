"""Post-commit hook: stamp ledger fragments with git commit SHAs.

For each fragment whose file list intersects the committed files, appends the
commit SHA to the fragment's git-commits list. A fragment can accumulate
multiple SHAs if its files were committed in stages — this is correct.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _get_head_sha(project_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root, capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _get_committed_files(project_root: Path) -> set[str]:
    result = subprocess.run(
        ["git", "show", "HEAD", "--name-only", "--format="],
        cwd=project_root, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _fragment_dir(project_root: Path) -> Path:
    return project_root / ".audiagentic" / "runtime" / "ledger" / "fragments"


def stamp_fragments_for_commit(project_root: Path) -> dict[str, list[str]]:
    """Stamp all fragments whose files intersect the HEAD commit.

    Returns a dict mapping commit SHA to list of stamped event-ids.
    No-ops cleanly if git is unavailable or no fragments directory exists.
    """
    sha = _get_head_sha(project_root)
    if not sha:
        return {}

    committed_files = _get_committed_files(project_root)
    if not committed_files:
        return {}

    fragments_dir = _fragment_dir(project_root)
    if not fragments_dir.exists():
        return {}

    stamped: list[str] = []
    for path in sorted(fragments_dir.glob("*.json")):
        try:
            fragment = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        fragment_files = set(fragment.get("files") or [])
        if not fragment_files.intersection(committed_files):
            continue

        commits: list[str] = list(fragment.get("git-commits") or [])
        if sha in commits:
            continue

        commits.append(sha)
        fragment["git-commits"] = commits
        path.write_text(json.dumps(fragment, indent=2, sort_keys=True), encoding="utf-8")
        stamped.append(fragment["event-id"])

    return {sha: stamped} if stamped else {}
