from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.jobs.reviews import build_review_bundle


def _report(review_id: str, reviewer_key: str, recommendation: str) -> dict[str, str]:
    return {"review-id": review_id, "reviewer-key": reviewer_key, "recommendation": recommendation}


def test_review_bundle_approves_when_all_pass() -> None:
    bundle = build_review_bundle(
        review_bundle_id="rvb_1",
        subject={"kind": "artifact", "artifact-id": "art_1"},
        required_reviews=2,
        aggregation_rule="all-pass",
        require_distinct_reviewers=True,
        reports=[_report("r1", "claude:cli:s1", "pass"), _report("r2", "codex:vscode:s2", "pass-with-notes")],
    )
    assert bundle["decision"] == "approved"
    assert bundle["status"] == "complete"


def test_review_bundle_blocks_on_rework() -> None:
    bundle = build_review_bundle(
        review_bundle_id="rvb_2",
        subject={"kind": "artifact", "artifact-id": "art_1"},
        required_reviews=1,
        aggregation_rule="all-pass",
        require_distinct_reviewers=True,
        reports=[_report("r1", "claude:cli:s1", "rework")],
    )
    assert bundle["decision"] == "rework"


def test_review_bundle_stays_open_with_duplicate_reviewers() -> None:
    bundle = build_review_bundle(
        review_bundle_id="rvb_3",
        subject={"kind": "artifact", "artifact-id": "art_1"},
        required_reviews=2,
        aggregation_rule="all-pass",
        require_distinct_reviewers=True,
        reports=[_report("r1", "claude:cli:s1", "pass"), _report("r2", "claude:cli:s1", "pass")],
    )
    assert bundle["decision"] == "pending"
    assert bundle["status"] == "open"
