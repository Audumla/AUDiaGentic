"""Periodic cleanup: retire dead records and finish worktrees whose merge is proven (DW01).

Nothing here is new authority: a record is dropped only when its directory is gone and git no
longer lists it, and a worktree is finished only when the same eligibility check ``finish``
requires says ``eligible`` (merge proven, clean, unused). Anything else is reported, not touched.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import forge, git

from . import eligibility, finish as finisher, records


def tidy(repo: Path, *, active_work, apply: bool = False, pull_requests=forge.pull_requests_for_branch,
         state_root: Path | None = None) -> dict[str, Any]:
    entries = git.list_worktrees(repo)
    live = {entry.path for entry in entries}
    stale = [record for record in records.read_records(repo, state_root=state_root).values()
             if Path(record.path) not in live and not Path(record.path).exists()]
    retired = []
    for record in stale:
        if apply and records.forget(repo, record.worktree_id, state_root=state_root):
            retired.append(record.path)
        elif not apply:
            retired.append(record.path)

    assessed = eligibility.assess_all(repo, active_work=active_work, pull_requests=pull_requests)["worktrees"]
    finished, left = [], []
    for row in assessed:
        if row["verdict"] != "eligible":
            left.append({"path": row["path"], "verdict": row["verdict"],
                         "blockers": [b["code"] for b in row["blockers"]]})
            continue
        if not apply:
            finished.append(row["path"])
            continue
        try:
            finisher.finish(repo, row["path"], active_work=active_work, pull_requests=pull_requests,
                            state_root=state_root)
            finished.append(row["path"])
        except AudiaGenticError as error:  # one refusal never stops the rest
            left.append({"path": row["path"], "verdict": "refused", "blockers": [error.code]})
    return {"applied": apply, "records-retired": retired, "worktrees-finished": finished, "left": left}
