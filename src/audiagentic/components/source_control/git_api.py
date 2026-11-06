"""Public git operations for other components (DW02).

The approved cross-component surface of source_control for git: exactly the
operations the worktree lifecycle uses, no more. Add an operation here only with
a named caller and an update to the approved-API table in ARCHITECTURE_STANDARDS.md.
``run_git`` and the other helpers in ``git_access`` stay internal, so a caller
cannot run an arbitrary git command through this module.

Queries are read-only and report an unknown fact as ``None``, never a guess. The
mutators are small and named; none rewrites history.
"""
from __future__ import annotations

from audiagentic.components.source_control.git_access import (
    WorktreeEntry,
    add_worktree,
    ahead_behind,
    branch_exists,
    bundle_heads,
    changes,
    commits_not_in,
    common_dir,
    conflicted_paths,
    create_bundle,
    create_ref,
    default_branch,
    delete_branch_at,
    delete_unmerged_branch,
    fetch,
    fetch_pull_head,
    ignored_entries,
    initialized_submodules,
    is_ancestor,
    list_worktrees,
    merge_abort,
    merge_base,
    merge_fast_forward,
    merge_in_progress,
    merge_ref,
    operation_in_progress,
    push_commit,
    remote_branch_commit,
    remote_url,
    remove_clean_worktree,
    resolve_commit,
    valid_branch_name,
    verify_bundle,
)

__all__ = [
    "WorktreeEntry",
    "add_worktree",
    "ahead_behind",
    "branch_exists",
    "bundle_heads",
    "changes",
    "commits_not_in",
    "common_dir",
    "conflicted_paths",
    "create_bundle",
    "create_ref",
    "default_branch",
    "delete_branch_at",
    "delete_unmerged_branch",
    "fetch",
    "fetch_pull_head",
    "ignored_entries",
    "initialized_submodules",
    "is_ancestor",
    "list_worktrees",
    "merge_abort",
    "merge_base",
    "merge_fast_forward",
    "merge_in_progress",
    "merge_ref",
    "operation_in_progress",
    "push_commit",
    "remote_branch_commit",
    "remote_url",
    "remove_clean_worktree",
    "resolve_commit",
    "valid_branch_name",
    "verify_bundle",
]
