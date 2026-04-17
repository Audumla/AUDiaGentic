from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from audiagentic.knowledge.config import load_config
from audiagentic.knowledge.llm import load_llm_job_state
from audiagentic.knowledge.models import DriftItem
from audiagentic.knowledge.sync import (
    apply_sync_proposal,
    cleanup_lifecycle,
    generate_sync_proposals,
)

ROOT = Path(__file__).resolve().parents[2]


def _seed_knowledge_project(root: Path) -> None:
    shutil.copytree(
        ROOT / ".audiagentic" / "knowledge",
        root / ".audiagentic" / "knowledge",
        dirs_exist_ok=True,
    )
    for rel in (
        "docs/knowledge/pages/guides",
        "docs/knowledge/data/meta/guides",
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


def _write_page(root: Path, page_id: str) -> None:
    content_path = root / "docs" / "knowledge" / "pages" / "guides" / f"{page_id}.md"
    meta_path = root / "docs" / "knowledge" / "data" / "meta" / "guides" / f"{page_id}.meta.yml"
    content_path.write_text(
        "## Summary\n\nSummary.\n\n## Current state\n\nCurrent.\n",
        encoding="utf-8",
    )
    meta_path.write_text(
        yaml.safe_dump(
            {
                "id": page_id,
                "title": "Lifecycle Page",
                "type": "guide",
                "status": "active",
                "summary": "Lifecycle test page.",
                "owners": ["core"],
                "updated_at": "2026-04-17",
                "source_refs": [],
                "sync_notes": {"last_sync": "2026-04-17T00:00:00+00:00", "sync_count": 0},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_generate_sync_proposals_sets_pending_status(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    config = load_config(tmp_path)

    proposal_paths = generate_sync_proposals(
        config,
        items=[
            DriftItem(
                page_id="guide-lifecycle",
                title="Lifecycle Guide",
                source_path="src/example.py",
                status="changed",
                message="Source changed",
            )
        ],
    )

    assert len(proposal_paths) == 1
    payload = yaml.safe_load(proposal_paths[0].read_text(encoding="utf-8"))
    assert payload["status"] == "pending"
    assert payload["status_updated_at"]


def test_apply_sync_proposal_archives_with_merged_status(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    _write_page(tmp_path, "guide-lifecycle")
    config = load_config(tmp_path)
    proposal_path = config.proposals_root / "proposal.yml"
    proposal_path.write_text(
        yaml.safe_dump(
            {
                "proposal_id": "proposal-001",
                "proposal_kind": "sync_review",
                "target_page_id": "guide-lifecycle",
                "proposal_mode": "deterministic",
                "generated_at": "2026-04-15T00:00:00+00:00",
                "status": "pending",
                "status_updated_at": "2026-04-15T00:00:00+00:00",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = apply_sync_proposal(config, proposal_path)

    assert result["status"] == "applied"
    archived_path = tmp_path / result["archived_path"]
    archived_payload = yaml.safe_load(archived_path.read_text(encoding="utf-8"))
    assert archived_payload["status"] == "merged"
    assert archived_payload["applied_at"]
    assert archived_payload["archived_at"]


def test_cleanup_lifecycle_prunes_terminal_jobs_and_old_proposals(tmp_path: Path) -> None:
    _seed_knowledge_project(tmp_path)
    config = load_config(tmp_path)
    now = datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc)

    config.llm_job_state_file.write_text(
        yaml.safe_dump(
            {
                "jobs": {
                    "job-old-complete": {
                        "submitted_at": (now - timedelta(days=10)).isoformat(),
                        "status": "completed",
                    },
                    "job-old-queued": {
                        "submitted_at": (now - timedelta(days=10)).isoformat(),
                        "status": "queued",
                    },
                    "job-recent-complete": {
                        "submitted_at": (now - timedelta(days=1)).isoformat(),
                        "status": "completed",
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    old_pending = config.proposals_root / "old-pending.yml"
    old_pending.write_text(
        yaml.safe_dump(
            {
                "proposal_id": "old-pending",
                "generated_at": (now - timedelta(days=40)).isoformat(),
                "status": "pending",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    recent_pending = config.proposals_root / "recent-pending.yml"
    recent_pending.write_text(
        yaml.safe_dump(
            {
                "proposal_id": "recent-pending",
                "generated_at": (now - timedelta(days=2)).isoformat(),
                "status": "pending",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    old_archived = config.archive_root / "old-archived.yml"
    old_archived.write_text(
        yaml.safe_dump(
            {
                "proposal_id": "old-archived",
                "archived_at": (now - timedelta(days=120)).isoformat(),
                "status": "merged",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = cleanup_lifecycle(config, now=now)

    jobs = load_llm_job_state(config)["jobs"]
    assert "job-old-complete" not in jobs
    assert "job-old-queued" in jobs
    assert "job-recent-complete" in jobs

    archived_pending = config.archive_root / "old-pending.yml"
    archived_pending_payload = yaml.safe_load(archived_pending.read_text(encoding="utf-8"))
    assert archived_pending_payload["status"] == "rejected"
    assert archived_pending_payload["status_reason"] == "expired_by_cleanup"
    assert recent_pending.exists()
    assert not old_archived.exists()

    assert "job-old-complete" in result["jobs"]["removed_job_ids"]
    assert "docs/knowledge/data/archive/old-pending.yml" in result["proposals"][
        "archived_pending_proposals"
    ]
    assert "docs/knowledge/data/archive/old-archived.yml" in result["proposals"][
        "deleted_archived_proposals"
    ]
