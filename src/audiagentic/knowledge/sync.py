from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from .config import KnowledgeConfig
from .diffing import normalize_text, summarize_structured_change, unified_diff_excerpt
from .markdown_io import load_pages
from .models import DriftItem


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_name(page_id: str, rel_path: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", rel_path)
    short = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:12]
    return f"{page_id}__{short}__{safe}.snapshot"


def load_sync_state(config: KnowledgeConfig) -> dict[str, Any]:
    if not config.sync_state_file.exists():
        return {"pages": {}, "manual_stale_pages": []}
    data = yaml.safe_load(config.sync_state_file.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"pages": {}, "manual_stale_pages": []}
    data.setdefault("pages", {})
    data.setdefault("manual_stale_pages", [])
    return data


def save_sync_state(config: KnowledgeConfig, state: dict[str, Any]) -> None:
    config.sync_state_file.parent.mkdir(parents=True, exist_ok=True)
    config.sync_state_file.write_text(
        yaml.safe_dump(
            state, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False
        ),
        encoding="utf-8",
    )


def record_sync_state(config: KnowledgeConfig, page_ids: list[str] | None = None) -> dict[str, Any]:
    pages = load_pages(config.pages_root, config.meta_root)
    state = load_sync_state(config)
    selected = set(page_ids or [])
    now = datetime.now(timezone.utc).isoformat()
    config.snapshots_root.mkdir(parents=True, exist_ok=True)
    for page in pages:
        if selected and page.page_id not in selected:
            continue
        refs = page.metadata.get("source_refs", []) or []
        page_state = state["pages"].setdefault(page.page_id, {"title": page.title, "sources": []})
        page_state["title"] = page.title
        page_state["sources"] = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            rel_path = str(ref.get("path", "")).strip()
            if not rel_path:
                continue
            source_path = config.root / rel_path
            digest = sha256_file(source_path) if source_path.exists() else None
            snapshot_file = None
            if source_path.exists():
                normalized = normalize_text(
                    source_path, source_path.read_text(encoding="utf-8", errors="replace")
                )
                snapshot_file = config.snapshots_root / snapshot_name(page.page_id, rel_path)
                snapshot_file.write_text(normalized, encoding="utf-8")
            page_state["sources"].append(
                {
                    "path": rel_path,
                    "fingerprint": digest,
                    "recorded_at": now,
                    "kind": ref.get("kind", "file"),
                    "snapshot": str(snapshot_file.relative_to(config.root))
                    if snapshot_file
                    else None,
                }
            )
    save_sync_state(config, state)
    return state


def scan_drift(config: KnowledgeConfig) -> list[DriftItem]:
    pages = load_pages(config.pages_root, config.meta_root)
    state = load_sync_state(config)
    manual_stale = set(str(x) for x in state.get("manual_stale_pages", []) or [])
    items: list[DriftItem] = []
    for page in pages:
        page_state = state.get("pages", {}).get(page.page_id)
        refs = page.metadata.get("source_refs", []) or []
        if page.page_id in manual_stale:
            items.append(
                DriftItem(
                    page.page_id,
                    page.title,
                    "<manual>",
                    "manual_stale",
                    "Page marked stale manually",
                )
            )
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            rel_path = str(ref.get("path", "")).strip()
            if not rel_path:
                continue
            source_path = config.root / rel_path
            old_record = _find_state_source(page_state, rel_path)
            old_text = _load_snapshot(config, old_record)
            if not source_path.exists():
                items.append(
                    DriftItem(
                        page.page_id,
                        page.title,
                        rel_path,
                        "missing",
                        "Source file is missing",
                        old_record.get("fingerprint") if old_record else None,
                        None,
                        unified_diff_excerpt(
                            old_text,
                            None,
                            rel_path,
                            config.diff_context_lines,
                            config.diff_max_lines,
                        )
                        if old_text
                        else None,
                    )
                )
                continue
            current_raw = source_path.read_text(encoding="utf-8", errors="replace")
            current_text = normalize_text(source_path, current_raw)
            current = sha256_file(source_path)
            details = summarize_structured_change(source_path, old_text, current_text)
            if old_record is None:
                items.append(
                    DriftItem(
                        page.page_id,
                        page.title,
                        rel_path,
                        "untracked",
                        "Source file is not yet fingerprinted",
                        None,
                        current,
                        unified_diff_excerpt(
                            None,
                            current_text,
                            rel_path,
                            config.diff_context_lines,
                            config.diff_max_lines,
                        ),
                        details,
                    )
                )
            elif old_record.get("fingerprint") != current:
                items.append(
                    DriftItem(
                        page.page_id,
                        page.title,
                        rel_path,
                        "changed",
                        "Source file fingerprint changed",
                        old_record.get("fingerprint"),
                        current,
                        unified_diff_excerpt(
                            old_text,
                            current_text,
                            rel_path,
                            config.diff_context_lines,
                            config.diff_max_lines,
                        ),
                        details,
                    )
                )
    return items


def mark_pages_stale(config: KnowledgeConfig, page_ids: list[str]) -> dict[str, Any]:
    state = load_sync_state(config)
    manual = set(str(x) for x in state.get("manual_stale_pages", []) or [])
    manual.update(page_ids)
    state["manual_stale_pages"] = sorted(manual)
    save_sync_state(config, state)
    return state


def clear_manual_stale(config: KnowledgeConfig, page_ids: list[str]) -> dict[str, Any]:
    state = load_sync_state(config)
    manual = set(str(x) for x in state.get("manual_stale_pages", []) or [])
    manual.difference_update(page_ids)
    state["manual_stale_pages"] = sorted(manual)
    save_sync_state(config, state)
    return state


def generate_sync_proposals(
    config: KnowledgeConfig, items: list[DriftItem] | None = None
) -> list[Path]:
    items = items or scan_drift(config)
    generated: list[Path] = []
    by_page: dict[str, list[DriftItem]] = {}
    for item in items:
        by_page.setdefault(item.page_id, []).append(item)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for page_id, page_items in by_page.items():
        proposal_path = config.proposals_root / f"{timestamp}-{page_id}-sync-review.yml"
        payload = {
            "proposal_id": f"{timestamp}-{page_id}-sync-review",
            "proposal_kind": "sync_review",
            "target_page_id": page_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "status_updated_at": datetime.now(timezone.utc).isoformat(),
            "summary": f"Source drift detected for {page_id}. Review and update the current-state page if needed.",
            "drift_items": [
                {
                    "source_path": item.source_path,
                    "status": item.status,
                    "message": item.message,
                    "fingerprint_before": item.fingerprint_before,
                    "fingerprint_now": item.fingerprint_now,
                    "details": item.details,
                    "diff_excerpt": item.diff_excerpt,
                }
                for item in page_items
            ],
            "suggested_steps": [
                "Review the changed source file(s).",
                "Decide whether the page is still current.",
                "Create or edit a content patch only if the current-state page should change.",
                "After review, record fresh sync fingerprints.",
            ],
            "actions": [],
        }
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        proposal_path.write_text(
            yaml.safe_dump(
                payload, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False
            ),
            encoding="utf-8",
        )
        generated.append(proposal_path)
    return generated


def _find_state_source(page_state: dict[str, Any] | None, rel_path: str) -> dict[str, Any] | None:
    if not page_state:
        return None
    for item in page_state.get("sources", []) or []:
        if str(item.get("path")) == rel_path:
            return item
    return None


def _load_snapshot(config: KnowledgeConfig, record: dict[str, Any] | None) -> str | None:
    if not record:
        return None
    rel = record.get("snapshot")
    if not rel:
        return None
    path = config.root / str(rel)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def apply_sync_proposal(config: KnowledgeConfig, proposal_path: Path) -> dict[str, Any]:
    """Apply a sync proposal deterministically.

    Reads the proposal file and applies the suggested changes to the target page.
    For deterministic mode proposals, this updates the page metadata and sync state
    without requiring manual review.

    Args:
        config: Knowledge configuration
        proposal_path: Path to the proposal YAML file

    Returns:
        Result dict with applied changes and status
    """
    if not proposal_path.exists():
        return {
            "status": "skipped",
            "reason": "Proposal file not found",
            "proposal_path": str(proposal_path),
        }

    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8")) or {}
    if not isinstance(proposal, dict):
        return {
            "status": "error",
            "reason": "Invalid proposal format",
            "proposal_path": str(proposal_path),
        }

    page_id = str(proposal.get("target_page_id", ""))
    proposal_mode = str(proposal.get("proposal_mode", "review_only"))

    # Only auto-apply deterministic mode proposals
    if proposal_mode != "deterministic":
        return {
            "status": "skipped",
            "reason": "Non-deterministic proposal requires manual review",
            "proposal_path": str(proposal_path),
            "mode": proposal_mode,
        }

    # Load the target page
    from .markdown_io import load_page_by_id

    page = load_page_by_id(config.pages_root, config.meta_root, page_id)
    if not page:
        return {
            "status": "skipped",
            "reason": f"Page not found: {page_id}",
            "proposal_path": str(proposal_path),
        }

    # Update the page metadata to reflect the sync
    from .utils import now_utc

    page.metadata["updated_at"] = now_utc().isoformat()
    if "sync_notes" in page.metadata:
        page.metadata["sync_notes"]["last_sync"] = now_utc().isoformat()
        page.metadata["sync_notes"]["sync_count"] = (
            page.metadata["sync_notes"].get("sync_count", 0) + 1
        )

    # Save the updated page
    from .markdown_io import save_page

    save_page(page)

    # Record the sync state
    record_sync_state(config, [page_id])

    # Move proposal to archive
    proposal["status"] = "merged"
    proposal["status_updated_at"] = now_utc().isoformat()
    proposal["applied_at"] = now_utc().isoformat()
    proposal["archived_at"] = now_utc().isoformat()
    proposal_path.write_text(
        yaml.safe_dump(
            proposal, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False
        ),
        encoding="utf-8",
    )
    archive_path = config.archive_root / proposal_path.name
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path = _dedupe_archive_path(archive_path)
    proposal_path.rename(archive_path)

    return {
        "status": "applied",
        "page_id": page_id,
        "proposal_path": str(proposal_path),
        "archived_path": str(archive_path),
        "synced_at": now_utc().isoformat(),
    }


def apply_all_proposals(
    config: KnowledgeConfig, proposal_paths: list[Path] | None = None
) -> list[dict[str, Any]]:
    """Apply all sync proposals in the proposals directory.

    Args:
        config: Knowledge configuration
        proposal_paths: Optional list of specific proposal paths to apply. If None, scans all proposals.

    Returns:
        List of result dicts for each applied proposal
    """
    results = []

    if proposal_paths:
        proposals_to_apply = proposal_paths
    else:
        # Scan all proposals in the proposals directory
        proposals_to_apply = []
        if config.proposals_root.exists():
            for path in config.proposals_root.rglob("*.yml"):
                if path.is_file():
                    proposals_to_apply.append(path)
            proposals_to_apply.extend(config.proposals_root.rglob("*.yaml"))

    for proposal_path in proposals_to_apply:
        result = apply_sync_proposal(config, proposal_path)
        results.append(result)

    return results


def cleanup_proposals(
    config: KnowledgeConfig,
    *,
    proposal_retention_days: int | None = None,
    archive_retention_days: int | None = None,
    prune_pending_proposals: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    proposal_retention = (
        config.proposal_retention_days
        if proposal_retention_days is None
        else int(proposal_retention_days)
    )
    archive_retention = (
        config.archive_retention_days
        if archive_retention_days is None
        else int(archive_retention_days)
    )
    proposal_cutoff = current_time - timedelta(days=proposal_retention)
    archive_cutoff = current_time - timedelta(days=archive_retention)

    archived_pending: list[str] = []
    stale_pending: list[str] = []
    deleted_archived: list[str] = []

    for proposal_path in _iter_proposal_files(config.proposals_root):
        proposal = _load_proposal_payload(proposal_path)
        proposal_time = _proposal_timestamp(proposal_path, proposal, "generated_at")
        if proposal_time >= proposal_cutoff:
            continue
        rel_path = proposal_path.relative_to(config.root).as_posix()
        if not prune_pending_proposals:
            stale_pending.append(rel_path)
            continue
        proposal["status"] = "rejected"
        proposal["status_reason"] = "expired_by_cleanup"
        proposal["status_updated_at"] = current_time.isoformat()
        proposal["archived_at"] = current_time.isoformat()
        proposal_path.write_text(
            yaml.safe_dump(
                proposal, sort_keys=False, allow_unicode=True, width=100, default_flow_style=False
            ),
            encoding="utf-8",
        )
        archive_path = _dedupe_archive_path(config.archive_root / proposal_path.name)
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        proposal_path.rename(archive_path)
        archived_pending.append(archive_path.relative_to(config.root).as_posix())

    for archive_path in _iter_proposal_files(config.archive_root):
        proposal = _load_proposal_payload(archive_path)
        archive_time = _proposal_timestamp(
            archive_path, proposal, "archived_at", "status_updated_at", "generated_at"
        )
        if archive_time >= archive_cutoff:
            continue
        deleted_archived.append(archive_path.relative_to(config.root).as_posix())
        archive_path.unlink()

    return {
        "proposal_retention_days": proposal_retention,
        "archive_retention_days": archive_retention,
        "prune_pending_proposals": prune_pending_proposals,
        "archived_pending_proposals": sorted(archived_pending),
        "stale_pending_proposals": sorted(stale_pending),
        "deleted_archived_proposals": sorted(deleted_archived),
    }


def cleanup_lifecycle(
    config: KnowledgeConfig,
    *,
    job_retention_days: int | None = None,
    proposal_retention_days: int | None = None,
    archive_retention_days: int | None = None,
    prune_pending_proposals: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    from .llm import cleanup_jobs

    current_time = now or datetime.now(timezone.utc)
    jobs = cleanup_jobs(config, retention_days=job_retention_days, now=current_time)
    proposals = cleanup_proposals(
        config,
        proposal_retention_days=proposal_retention_days,
        archive_retention_days=archive_retention_days,
        prune_pending_proposals=prune_pending_proposals,
        now=current_time,
    )
    return {
        "cleaned_at": current_time.isoformat(),
        "jobs": jobs,
        "proposals": proposals,
    }


def _load_proposal_payload(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _iter_proposal_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files = [path for path in root.rglob("*.yml") if path.is_file()]
    files.extend(path for path in root.rglob("*.yaml") if path.is_file())
    return sorted(files)


def _proposal_timestamp(path: Path, proposal: dict[str, Any], *keys: str) -> datetime:
    for key in keys:
        parsed = _parse_iso_datetime(proposal.get(key))
        if parsed is not None:
            return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dedupe_archive_path(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
