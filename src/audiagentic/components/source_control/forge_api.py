"""Public code-forge operations for other components (DW02).

The approved cross-component surface of source_control for the forge (GitHub
through ``gh``): pull-request and repository reads plus three named writes
(open a pull request, set its title, request auto-merge). It never merges, closes
or comments. A fact the forge cannot give is an error, never a guess.
"""
from __future__ import annotations

from audiagentic.components.source_control.forge_access import (
    PullRequest,
    RepositoryIdentity,
    create_pull_request,
    enable_auto_merge,
    pull_request,
    pull_requests_for_branch,
    repository_identity,
    set_pull_request_title,
)

__all__ = [
    "PullRequest",
    "RepositoryIdentity",
    "create_pull_request",
    "enable_auto_merge",
    "pull_request",
    "pull_requests_for_branch",
    "repository_identity",
    "set_pull_request_title",
]
