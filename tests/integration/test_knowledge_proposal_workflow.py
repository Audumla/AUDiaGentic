from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from audiagentic.knowledge.config import load_config
from audiagentic.knowledge.lifecycle import (
    accept_proposal,
    apply_proposal,
    get_proposal,
    reject_proposal,
)

ROOT = Path(__file__).resolve().parents[2]


def _seed_knowledge_project(root: Path) -> None:
    shutil.copytree(
        ROOT / ".audiagentic" / "knowledge",
        root / ".audiagentic" / "knowledge",
        dirs_exist_ok=True,
    )
    for rel in (
        "docs/knowledge/pages/tools",
        "docs/knowledge/data/meta/tools",
        "docs/knowledge/data/state",
        "docs/knowledge/data/proposals",
        "docs/knowledge/data/archive",
    ):
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / "docs" / "knowledge" / "data" / "state" / "sync-state.yml").write_text(
        yaml.safe_dump({"pages": {}, "manual_stale_pages": []}, sort_keys=False),
        encoding="utf-8",
    )
    (root / "docs" / "knowledge" / "data" / "state" / "llm-jobs.yml").write_text(
        yaml.safe_dump({"jobs": {}}, sort_keys=False),
        encoding="utf-8",
    )
    (root / "docs" / "knowledge" / "pages" / "tools" / "tool-cli.md").write_text(
        "## Summary\n\nOld summary.\n\n## Current state\n\nOld state.\n\n## How to use\n\nUse.\n",
        encoding="utf-8",
    )
    (root / "docs" / "knowledge" / "data" / "meta" / "tools" / "tool-cli.meta.yml").write_text(
        yaml.safe_dump(
            {
                "id": "tool-cli",
                "title": "tool-cli",
                "type": "tool",
                "status": "active",
                "summary": "Tool page",
                "owners": ["core"],
                "updated_at": "2026-04-17",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_accept_proposal_marks_status(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    config = load_config(tmp_path)
    proposal_path = config.proposals_root / "proposal.yml"
    proposal_path.write_text(
        yaml.safe_dump(
            {
                "proposal_id": "proposal-accept",
                "proposal_kind": "event_review",
                "target_page_id": "tool-cli",
                "generated_at": "2026-04-17T00:00:00+00:00",
                "status": "pending",
                "actions": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = accept_proposal(config, "proposal-accept", note="looks valid")

    assert result["status"] == "accepted"
    reloaded = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    assert reloaded["status"] == "accepted"
    assert reloaded["review_notes"] == ["looks valid"]


def test_reject_proposal_archives_file(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    config = load_config(tmp_path)
    proposal_path = config.proposals_root / "proposal.yml"
    proposal_path.write_text(
        yaml.safe_dump(
            {
                "proposal_id": "proposal-reject",
                "proposal_kind": "event_review",
                "target_page_id": "tool-cli",
                "generated_at": "2026-04-17T00:00:00+00:00",
                "status": "pending",
                "actions": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = reject_proposal(config, "proposal-reject", note="no doc change")

    assert result["status"] == "rejected"
    assert not proposal_path.exists()
    archived = config.archive_root / proposal_path.name
    assert archived.exists()
    archived_payload = yaml.safe_load(archived.read_text(encoding="utf-8"))
    assert archived_payload["status_reason"] == "manual_rejection"
    assert archived_payload["review_notes"] == ["no doc change"]


def test_apply_proposal_executes_patch_actions_and_archives(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    config = load_config(tmp_path)
    proposal_path = config.proposals_root / "proposal.yml"
    proposal_path.write_text(
        yaml.safe_dump(
            {
                "proposal_id": "proposal-apply",
                "proposal_kind": "event_review",
                "target_page_id": "tool-cli",
                "generated_at": "2026-04-17T00:00:00+00:00",
                "status": "accepted",
                "actions": [
                    {
                        "action": "replace_section",
                        "section": "Current state",
                        "body": "New state from accepted proposal.",
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = apply_proposal(config, "proposal-apply", note="applied")

    assert result["status"] == "applied"
    page_text = (tmp_path / "docs" / "knowledge" / "pages" / "tools" / "tool-cli.md").read_text(
        encoding="utf-8"
    )
    assert "New state from accepted proposal." in page_text
    assert not proposal_path.exists()
    archived = config.archive_root / proposal_path.name
    archived_payload = yaml.safe_load(archived.read_text(encoding="utf-8"))
    assert archived_payload["status"] == "merged"
    assert archived_payload["review_notes"] == ["applied"]


def test_get_proposal_reads_active_and_archived(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    config = load_config(tmp_path)
    active = config.proposals_root / "active.yml"
    archived = config.archive_root / "archived.yml"
    active.write_text(
        yaml.safe_dump({"proposal_id": "active-proposal", "status": "pending"}, sort_keys=False),
        encoding="utf-8",
    )
    archived.write_text(
        yaml.safe_dump({"proposal_id": "archived-proposal", "status": "merged"}, sort_keys=False),
        encoding="utf-8",
    )

    assert get_proposal(config, "active-proposal") is not None
    assert get_proposal(config, "archived-proposal") is not None


def test_accept_then_apply_review_update_generates_patch_actions(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    config = load_config(tmp_path)
    proposal_path = config.proposals_root / "proposal.yml"
    proposal_path.write_text(
        yaml.safe_dump(
            {
                "proposal_id": "proposal-review-update",
                "proposal_kind": "event_review",
                "target_page_id": "tool-cli",
                "generated_at": "2026-04-17T00:00:00+00:00",
                "status": "pending",
                "recommendation": "review_update",
                "assessment": {
                    "reason": "Durable CLI behavior may have changed.",
                },
                "events": [
                    {
                        "event_id": "runtime-planning::planning.item.state.changed::task::task-1::done::manual"
                    }
                ],
                "actions": [
                    {
                        "action": "review_section",
                        "section": "Current state",
                        "intent": "confirm docs",
                    },
                    {
                        "action": "review_section",
                        "section": "How to use",
                        "intent": "confirm docs",
                    },
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    accepted = accept_proposal(config, "proposal-review-update", note="generate patch")

    assert accepted["status"] == "accepted"
    assert accepted["patch_actions"]
    assert accepted["patch_actions"][0]["action"] == "append_section"

    result = apply_proposal(config, "proposal-review-update", note="applied generated patch")

    assert result["status"] == "applied"
    page_text = (tmp_path / "docs" / "knowledge" / "pages" / "tools" / "tool-cli.md").read_text(
        encoding="utf-8"
    )
    assert "Accepted proposal `proposal-review-update`." in page_text
    assert "Sections to review:" in page_text
    assert "Current state" in page_text
    archived = config.archive_root / proposal_path.name
    archived_payload = yaml.safe_load(archived.read_text(encoding="utf-8"))
    assert archived_payload["status"] == "merged"
    assert archived_payload["patch_actions"]
