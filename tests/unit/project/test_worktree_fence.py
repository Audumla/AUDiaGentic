"""DW01 slice 3a: the drain fence in front of MCP worktree resolution, and the gateway active-work query."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway import api as gateway
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.mcp.worktree import resolve_worktree
from audiagentic.foundation.system import worktree_drain

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


@pytest.fixture
def worktree(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    root = tmp_path / "wt"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True, env={**os.environ, **ENV})
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "c0"], cwd=root, check=True,
                   env={**os.environ, **ENV})
    return root.resolve()


def test_a_draining_worktree_accepts_no_new_mcp_work_until_the_fence_lifts(worktree: Path) -> None:
    assert resolve_worktree(str(worktree)).path == worktree
    worktree_drain.begin(worktree, reason="finish in progress")
    assert worktree_drain.is_draining(worktree)

    with pytest.raises(AudiaGenticError) as raised:
        resolve_worktree(str(worktree))
    assert raised.value.code == "CFG-MCPWT-006"
    assert raised.value.details["reason"] == "finish in progress"

    worktree_drain.begin(worktree, reason="again")  # idempotent
    worktree_drain.end(worktree)
    worktree_drain.end(worktree)  # idempotent
    assert not worktree_drain.is_draining(worktree)
    assert resolve_worktree(str(worktree)).path == worktree


def test_the_fence_is_per_worktree(worktree: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=other, check=True)
    worktree_drain.begin(worktree, reason="x")
    assert resolve_worktree(str(other.resolve())).path == other.resolve()


def test_active_work_lists_unfinished_requests_and_sessions_only(worktree: Path) -> None:
    assert gateway.worktree_active_work(worktree) == {"requests": [], "sessions": []}

    live = store.build_record(execution_profile_id="default", prompt_body="x")
    done = store.build_record(execution_profile_id="default", prompt_body="y")
    store.write_record(worktree, live)
    store.write_record(worktree, done)
    store.transition_record(worktree, done["request-id"], "cancelled")

    active_session = sessions_store.build_session_record(execution_profile_id="default", provider_id="local")
    closed_session = sessions_store.build_session_record(execution_profile_id="default", provider_id="local")
    closed_session["state"] = "closed"
    sessions_store.write_session_record(worktree, active_session)
    sessions_store.write_session_record(worktree, closed_session)

    assert gateway.worktree_active_work(worktree) == {
        "requests": [live["request-id"]], "sessions": [active_session["session-id"]]}
