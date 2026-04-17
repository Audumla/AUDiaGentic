"""Lifecycle query API for knowledge proposals and jobs.

Thin query layer over existing YAML state files:
- Proposals: docs/knowledge/proposals/*.yml
- Jobs: docs/knowledge/state/llm-jobs.yml

No new persistence — reads existing state written by sync.py and llm.py.
"""

from __future__ import annotations

from typing import Any

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
