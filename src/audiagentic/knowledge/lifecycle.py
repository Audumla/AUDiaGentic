"""Lifecycle query API for knowledge proposals and jobs.

Thin query layer over existing YAML state files:
- Proposals: docs/knowledge/proposals/*.yml
- Jobs: docs/knowledge/state/llm-jobs.yml

No new persistence — reads existing state written by sync.py and llm.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import KnowledgeConfig
from .utils import load_yaml_file


def list_proposals(config: KnowledgeConfig, status: str | None = None) -> list[dict[str, Any]]:
    """List all proposals, optionally filtered by status.

    Args:
        config: Knowledge config
        status: Filter by status ('pending', 'merged', 'rejected'). None = all.

    Returns:
        List of proposal dicts, sorted by generated_at descending.
    """
    proposals = []
    proposals_root = config.proposals_root
    archive_root = config.archive_root

    for search_dir in [proposals_root, archive_root]:
        if not search_dir.exists():
            continue
        for path in sorted(search_dir.rglob("*.yml")):
            data = load_yaml_file(path, {})
            if not isinstance(data, dict) or "proposal_id" not in data:
                continue
            if status is not None and data.get("status") != status:
                continue
            proposals.append({**data, "_path": str(path)})

    proposals.sort(key=lambda p: str(p.get("generated_at", "")), reverse=True)
    return proposals


def get_proposal(config: KnowledgeConfig, proposal_id: str) -> dict[str, Any] | None:
    """Get a single proposal by ID.

    Args:
        config: Knowledge config
        proposal_id: Proposal ID to look up

    Returns:
        Proposal dict or None if not found.
    """
    for proposal in list_proposals(config):
        if proposal.get("proposal_id") == proposal_id:
            return proposal
    return None


def list_jobs(config: KnowledgeConfig, status: str | None = None) -> list[dict[str, Any]]:
    """List LLM jobs, optionally filtered by status.

    Args:
        config: Knowledge config
        status: Filter by status ('queued', 'running', 'completed', 'failed'). None = all.

    Returns:
        List of job dicts, sorted by created_at descending.
    """
    jobs_file = config.llm_job_state_file
    data = load_yaml_file(jobs_file, {})
    if not isinstance(data, dict):
        return []

    all_jobs = data.get("jobs", {})
    if not isinstance(all_jobs, dict):
        return []

    jobs = []
    for job_id, job_data in all_jobs.items():
        if not isinstance(job_data, dict):
            continue
        entry = {"job_id": job_id, **job_data}
        if status is not None and entry.get("status") != status:
            continue
        jobs.append(entry)

    jobs.sort(key=lambda j: str(j.get("created_at", "")), reverse=True)
    return jobs


def get_job(config: KnowledgeConfig, job_id: str) -> dict[str, Any] | None:
    """Get a single job by ID.

    Args:
        config: Knowledge config
        job_id: Job ID to look up

    Returns:
        Job dict or None if not found.
    """
    jobs_file = config.llm_job_state_file
    data = load_yaml_file(jobs_file, {})
    if not isinstance(data, dict):
        return None
    all_jobs = data.get("jobs", {})
    if not isinstance(all_jobs, dict):
        return None
    job_data = all_jobs.get(job_id)
    if job_data is None:
        return None
    return {"job_id": job_id, **job_data}


def lifecycle_summary(config: KnowledgeConfig) -> dict[str, Any]:
    """Return counts of proposals and jobs by status.

    Returns:
        Dict with 'proposals' and 'jobs' keys, each containing status counts.
    """
    proposals = list_proposals(config)
    jobs = list_jobs(config)

    proposal_counts: dict[str, int] = {}
    for p in proposals:
        s = str(p.get("status", "unknown"))
        proposal_counts[s] = proposal_counts.get(s, 0) + 1

    job_counts: dict[str, int] = {}
    for j in jobs:
        s = str(j.get("status", "unknown"))
        job_counts[s] = job_counts.get(s, 0) + 1

    return {
        "proposals": {
            "total": len(proposals),
            "by_status": proposal_counts,
        },
        "jobs": {
            "total": len(jobs),
            "by_status": job_counts,
        },
    }


def accept_proposal(
    config: KnowledgeConfig, proposal_id: str, note: str | None = None
) -> dict[str, Any]:
    proposal = _require_active_proposal(config, proposal_id)
    path = Path(str(proposal["_path"]))
    proposal["status"] = "accepted"
    proposal["status_updated_at"] = _now_iso()
    patch_actions = _generate_patch_actions(proposal)
    if patch_actions:
        proposal["patch_actions"] = patch_actions
    if note:
        proposal.setdefault("review_notes", []).append(note)
    _save_proposal(path, proposal)
    return {**proposal, "_path": str(path)}


def reject_proposal(
    config: KnowledgeConfig, proposal_id: str, note: str | None = None
) -> dict[str, Any]:
    proposal = _require_active_proposal(config, proposal_id)
    path = Path(str(proposal["_path"]))
    proposal["status"] = "rejected"
    proposal["status_reason"] = "manual_rejection"
    proposal["status_updated_at"] = _now_iso()
    proposal["archived_at"] = _now_iso()
    if note:
        proposal.setdefault("review_notes", []).append(note)
    _save_proposal(path, proposal)
    archive_path = config.archive_root / path.name
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    if archive_path.exists():
        archive_path = _dedupe_archive_path(archive_path)
    path.rename(archive_path)
    proposal["_path"] = str(archive_path)
    return proposal


def apply_proposal(
    config: KnowledgeConfig, proposal_id: str, note: str | None = None
) -> dict[str, Any]:
    from .patches import apply_patch_file
    from .sync import apply_sync_proposal

    proposal = _require_active_proposal(config, proposal_id)
    path = Path(str(proposal["_path"]))
    actions = proposal.get("patch_actions", proposal.get("actions", []))
    executable_actions = {
        "set_metadata",
        "add_list_item",
        "remove_list_item",
        "replace_section",
        "append_section",
        "create_page",
    }

    if proposal.get("proposal_kind") == "sync_review" and proposal.get("proposal_mode") == "deterministic":
        return apply_sync_proposal(config, path)

    if isinstance(actions, list) and actions and all(
        isinstance(action, dict) and str(action.get("action", "")) in executable_actions
        for action in actions
    ):
        if proposal.get("patch_actions"):
            proposal["review_actions"] = proposal.get("actions", [])
            proposal["actions"] = proposal["patch_actions"]
            _save_proposal(path, proposal)
        result = apply_patch_file(config, path)
        updated = _load_active_or_archived_proposal(path)
        updated["status"] = "merged"
        updated["status_updated_at"] = _now_iso()
        updated["applied_at"] = _now_iso()
        updated["archived_at"] = _now_iso()
        if note:
            updated.setdefault("review_notes", []).append(note)
        _save_proposal(path, updated)
        archive_path = config.archive_root / path.name
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        if archive_path.exists():
            archive_path = _dedupe_archive_path(archive_path)
        path.rename(archive_path)
        return {
            "status": "applied",
            "proposal_id": proposal_id,
            "archived_path": str(archive_path),
            "result": {
                "changed": result.changed,
                "path": result.path,
                "actions_applied": result.actions_applied,
                "message": result.message,
            },
        }

    raise ValueError(
        "Proposal does not contain executable patch actions. Accept/reject it, or convert it into a patch proposal first."
    )


def _generate_patch_actions(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    actions = proposal.get("actions", [])
    recommendation = str(proposal.get("recommendation", ""))
    if not isinstance(actions, list) or recommendation != "review_update":
        return []

    review_sections = [
        str(action.get("section"))
        for action in actions
        if isinstance(action, dict) and str(action.get("action", "")) == "review_section"
    ]
    if not review_sections:
        return []

    assessment = proposal.get("assessment", {}) if isinstance(proposal.get("assessment"), dict) else {}
    reason = str(assessment.get("reason", "Accepted review proposal"))
    event_ids = [
        str(event.get("event_id"))
        for event in proposal.get("events", [])
        if isinstance(event, dict) and event.get("event_id")
    ]
    lines = [
        f"Accepted proposal `{proposal.get('proposal_id', '<proposal>')}`.",
        f"Reason: {reason}",
        "Sections to review:",
        *[f"- {section}" for section in review_sections],
    ]
    if event_ids:
        lines.extend(
            [
                "Source events:",
                *[f"- `{event_id}`" for event_id in event_ids[:5]],
            ]
        )

    return [
        {
            "action": "append_section",
            "section": "Sync notes",
            "body": "\n".join(lines),
        }
    ]


def _require_active_proposal(config: KnowledgeConfig, proposal_id: str) -> dict[str, Any]:
    proposal = get_proposal(config, proposal_id)
    if proposal is None:
        raise ValueError(f"Proposal not found: {proposal_id}")
    path = Path(str(proposal["_path"]))
    if config.archive_root in path.parents:
        raise ValueError(f"Proposal is archived and cannot be modified: {proposal_id}")
    return proposal


def _load_active_or_archived_proposal(path: Path) -> dict[str, Any]:
    data = load_yaml_file(path, {})
    if not isinstance(data, dict):
        raise ValueError(f"Invalid proposal format: {path}")
    return data


def _save_proposal(path: Path, proposal: dict[str, Any]) -> None:
    payload = dict(proposal)
    payload.pop("_path", None)
    path.write_text(
        yaml.safe_dump(
            payload, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False
        ),
        encoding="utf-8",
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedupe_archive_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
