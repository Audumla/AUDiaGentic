from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .capability import doctor
from .config import KnowledgeConfig
from .events import process_events, record_event_baseline, scan_events
from .importers import scaffold_page, seed_from_manifest
from .search import search_pages
from .sync import (
    apply_all_proposals,
    cleanup_lifecycle,
    generate_sync_proposals,
    record_sync_state,
    scan_drift,
)


def execute_deterministic_action(
    config: KnowledgeConfig,
    action_registry: dict[str, dict[str, Any]],
    action_id: str,
    runtime_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .registry import resolve_registry_handler

    runtime_args = runtime_args or {}
    handler, defaults = resolve_registry_handler(action_registry, action_id)
    merged = {**defaults, **runtime_args}
    return handler(config=config, action_id=action_id, action_args=merged)


# Built-in deterministic handlers


def action_scan_drift(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    return {"action_id": action_id, "result": [asdict(item) for item in scan_drift(config)]}


def action_generate_sync_proposals(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "result": [str(path.relative_to(config.root)) for path in generate_sync_proposals(config)],
    }


def action_apply_proposals(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    proposal_paths = action_args.get("proposal_paths")
    if proposal_paths:
        paths = [config.root / str(p) for p in proposal_paths]
    else:
        paths = None
    results = apply_all_proposals(config, paths)
    return {"action_id": action_id, "result": results}


def action_cleanup_lifecycle(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    result = cleanup_lifecycle(
        config,
        job_retention_days=action_args.get("job_retention_days"),
        proposal_retention_days=action_args.get("proposal_retention_days"),
        archive_retention_days=action_args.get("archive_retention_days"),
        prune_pending_proposals=bool(action_args.get("prune_pending_proposals", True)),
        dedupe_pending_proposals=bool(action_args.get("dedupe_pending_proposals", True)),
    )
    return {"action_id": action_id, "result": result}


def action_record_sync(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    page_ids = action_args.get("page_ids")
    return {"action_id": action_id, "result": record_sync_state(config, page_ids)}


def action_scan_events(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    return {"action_id": action_id, "result": [asdict(item) for item in scan_events(config)]}


def action_process_events(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    return {"action_id": action_id, "result": process_events(config)}


def action_record_event_baseline(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    return {"action_id": action_id, "result": record_event_baseline(config)}


def action_seed_from_manifest(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    manifest_path = str(action_args.get("manifest_path", ""))
    if not manifest_path:
        raise ValueError("manifest_path is required")
    result = seed_from_manifest(
        config,
        (config.root / manifest_path).resolve(),
        record_sync=bool(action_args.get("record_sync", False)),
        update_existing=bool(action_args.get("update_existing", False)),
    )
    return {"action_id": action_id, "result": [asdict(item) for item in result]}


def action_scaffold_page(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    result = scaffold_page(
        config,
        page_id=str(action_args["page_id"]),
        title=str(action_args["title"]),
        page_type=str(action_args["page_type"]),
        summary=str(action_args["summary"]),
        owners=[str(x) for x in action_args.get("owners", [])],
        tags=[str(x) for x in action_args.get("tags", [])],
        related=[str(x) for x in action_args.get("related", [])],
        source_refs=list(action_args.get("source_refs", [])),
        update_existing=bool(action_args.get("update_existing", False)),
    )
    return {"action_id": action_id, "result": asdict(result)}


def action_search_pages(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    query = str(action_args.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")
    limit = int(action_args.get("limit", 10))
    return {
        "action_id": action_id,
        "result": [asdict(item) for item in search_pages(config, query, limit=limit)],
    }


def action_doctor(
    *, config: KnowledgeConfig, action_id: str, action_args: dict[str, Any]
) -> dict[str, Any]:
    return {"action_id": action_id, "result": doctor(config)}
