from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .actions import execute_deterministic_action
from .bootstrap import bootstrap_project
from .capability import doctor, show_capability_contract, show_install_profiles
from .config import load_config
from .events import load_event_adapters, process_events, record_event_baseline, scan_events
from .hooks import evaluate_source, load_hooks
from .importers import scaffold_page, seed_from_manifest
from .index_maintenance import maintain_index_pages, refresh_index, validate_index_links
from .lifecycle import (
    accept_proposal,
    apply_proposal,
    get_proposal,
    lifecycle_summary,
    list_proposals,
    reject_proposal,
)
from .llm import (
    answer_question,
    bootstrap_project_knowledge,
    draft_sync_proposal,
    get_job_result,
    get_job_status,
    list_profiles,
    show_execution_registry,
    submit_profile_job,
)
from .markdown_io import load_page_by_id
from .navigation import explain_navigation_contract, suggest_navigation
from .patches import PatchError, apply_patch_file
from .registry import (
    load_action_registry,
    load_event_action_registry,
    load_importer_registry,
    load_llm_provider_registry,
    load_llm_task_policies,
)
from .search import search_pages
from .status import build_status
from .sync import (
    apply_all_proposals,
    cleanup_lifecycle,
    clear_manual_stale,
    generate_sync_proposals,
    mark_pages_stale,
    record_sync_state,
    scan_drift,
)
from .validation import validate_vault


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "bootstrap":
        payload = bootstrap_project(
            Path(args.target).resolve(),
            knowledge_root=args.knowledge_root,
            config_relpath=args.config_relpath,
            force=args.force,
            capability_profile=args.capability_profile,
            host_profile=args.host_profile,
        )
        _print(payload, args.json)
        return

    root = Path(args.root).resolve()
    config = load_config(root, getattr(args, "config", None))
    if args.command == "validate":
        payload = [asdict(issue) for issue in validate_vault(config)]
        _print(payload, args.json)
        raise SystemExit(1 if any(item["severity"] == "error" for item in payload) else 0)
    if args.command == "search":
        payload = [asdict(r) for r in search_pages(config, args.query, limit=args.limit)]
        _print(payload, args.json, search_mode=True)
        return
    if args.command == "answer-question":
        _print(
            answer_question(
                config,
                args.question,
                limit=args.limit,
                allow_llm=(None if not args.allow_llm and not args.no_llm else args.allow_llm),
                mode=args.mode,
            ),
            args.json,
        )
        return
    if args.command == "draft-sync-proposal":
        _print(
            draft_sync_proposal(
                config,
                page_id=args.page_id,
                allow_llm=(None if not args.allow_llm and not args.no_llm else args.allow_llm),
                mode=args.mode,
            ),
            args.json,
        )
        return
    if args.command == "list-profiles":
        _print(list_profiles(config), args.json)
        return
    if args.command == "show-execution-registry":
        _print(show_execution_registry(config), args.json)
        return
    if args.command == "show-install-profiles":
        _print(show_install_profiles(), args.json)
        return
    if args.command == "show-capability-contract":
        _print(show_capability_contract(config), args.json)
        return
    if args.command == "doctor":
        _print(doctor(config), args.json)
        raise SystemExit(0 if doctor(config).get("ok") else 1)
    if args.command == "bootstrap-project-knowledge":
        _print(
            bootstrap_project_knowledge(
                config,
                manifest=args.manifest,
                allow_llm=(None if not args.allow_llm and not args.no_llm else args.allow_llm),
                mode=args.mode,
            ),
            args.json,
        )
        return
    if args.command == "submit-profile-job":
        payload = json.loads(args.payload) if args.payload else {}
        _print(
            submit_profile_job(
                config,
                args.task_name,
                payload,
                mode=args.mode,
                allow_llm=(None if not args.allow_llm and not args.no_llm else args.allow_llm),
            ),
            args.json,
        )
        return
    if args.command == "get-job-status":
        _print(get_job_status(config, args.job_id), args.json)
        return
    if args.command == "get-job-result":
        _print(get_job_result(config, args.job_id), args.json)
        return
    if args.command == "prune-events":
        from .events import prune_event_state

        payload = prune_event_state(config, max_events=args.max_events)
        _print(payload, args.json)
        return
    if args.command == "get-page":
        page = load_page_by_id(config.pages_root, config.meta_root, args.page_id)
        if page is None:
            print(f"Page not found: {args.page_id}", file=sys.stderr)
            raise SystemExit(1)
        payload = {
            "page_id": page.page_id,
            "title": page.title,
            "type": page.page_type,
            "metadata": page.metadata,
            "path": str(page.content_path.relative_to(config.root)),
            "sections": [{"title": s.title, "body": s.body} for s in page.sections],
        }
        _print(payload, args.json)
        return
    if args.command == "status":
        _print(build_status(config), args.json)
        return
    if args.command == "apply-patch":
        try:
            payload = asdict(apply_patch_file(config, Path(args.patch).resolve()))
        except PatchError as exc:
            print(f"Patch failed: {exc}", file=sys.stderr)
            raise SystemExit(1)
        _print(payload, args.json)
        return
    if args.command == "scan-drift":
        payload = [asdict(item) for item in scan_drift(config)]
        _print(payload, args.json)
        raise SystemExit(1 if payload else 0)
    if args.command == "record-sync":
        _print(record_sync_state(config, args.page_id or None), args.json)
        return
    if args.command == "mark-stale":
        _print(mark_pages_stale(config, args.page_id), args.json)
        return
    if args.command == "clear-stale":
        _print(clear_manual_stale(config, args.page_id), args.json)
        return
    if args.command == "generate-sync-proposals":
        _print(
            [str(path.relative_to(config.root)) for path in generate_sync_proposals(config)],
            args.json,
        )
        return
    if args.command == "apply-proposals":
        _print(apply_all_proposals(config), args.json)
        return
    if args.command == "cleanup-lifecycle":
        _print(
            cleanup_lifecycle(
                config,
                job_retention_days=args.job_retention_days,
                proposal_retention_days=args.proposal_retention_days,
                archive_retention_days=args.archive_retention_days,
                prune_pending_proposals=not args.keep_pending_proposals,
                dedupe_pending_proposals=not args.keep_duplicate_proposals,
            ),
            args.json,
        )
        return
    if args.command == "show-hooks":
        _print(load_hooks(config), args.json)
        return
    if args.command == "evaluate-source":
        _print(evaluate_source(config, args.relative_path), args.json)
        return
    if args.command == "show-event-adapters":
        _print(load_event_adapters(config), args.json)
        return
    if args.command == "list-proposals":
        _print(list_proposals(config, status=args.status), args.json)
        return
    if args.command == "get-proposal":
        proposal = get_proposal(config, args.proposal_id)
        if proposal is None:
            print(f"Proposal not found: {args.proposal_id}", file=sys.stderr)
            raise SystemExit(1)
        _print(proposal, args.json)
        return
    if args.command == "proposal-summary":
        _print(lifecycle_summary(config), args.json)
        return
    if args.command == "accept-proposal":
        _print(accept_proposal(config, args.proposal_id, note=args.note), args.json)
        return
    if args.command == "reject-proposal":
        _print(reject_proposal(config, args.proposal_id, note=args.note), args.json)
        return
    if args.command == "apply-proposal":
        _print(apply_proposal(config, args.proposal_id, note=args.note), args.json)
        return
    if args.command == "show-importer-registry":
        _print(load_importer_registry(config), args.json)
        return
    if args.command == "show-action-registry":
        _print(load_action_registry(config), args.json)
        return
    if args.command == "show-event-action-registry":
        _print(load_event_action_registry(config), args.json)
        return
    if args.command == "show-llm-registry":
        _print(
            {
                "providers": load_llm_provider_registry(config),
                "task_policies": load_llm_task_policies(config),
            },
            args.json,
        )
        return
    if args.command == "show-navigation":
        _print(explain_navigation_contract(config), args.json)
        return
    if args.command == "navigate":
        _print(suggest_navigation(config, args.goal, limit=args.limit), args.json)
        return
    if args.command == "list-actions":
        _print(sorted(load_action_registry(config).keys()), args.json)
        return
    if args.command == "run-action":
        runtime_args = json.loads(args.arguments) if args.arguments else {}
        _print(
            execute_deterministic_action(
                config, load_action_registry(config), args.action_id, runtime_args
            ),
            args.json,
        )
        return
    if args.command == "scan-events":
        payload = [asdict(item) for item in scan_events(config)]
        _print(payload, args.json)
        raise SystemExit(1 if payload else 0)
    if args.command == "process-events":
        _print(process_events(config), args.json)
        return
    if args.command == "record-event-baseline":
        _print(record_event_baseline(config), args.json)
        return
    if args.command == "seed-from-manifest":
        payload = [
            asdict(item)
            for item in seed_from_manifest(
                config,
                (config.root / args.manifest).resolve(),
                record_sync=args.record_sync,
                update_existing=args.update_existing,
            )
        ]
        _print(payload, args.json)
        return
    if args.command == "scaffold-page":
        payload = asdict(
            scaffold_page(
                config,
                page_id=args.page_id,
                title=args.title,
                page_type=args.page_type,
                summary=args.summary,
                owners=args.owner,
                tags=args.tag,
                related=args.related,
                source_refs=json.loads(args.source_refs) if args.source_refs else None,
                update_existing=args.update_existing,
            )
        )
        _print(payload, args.json)
        return
    if args.command == "maintain-index":
        updated = maintain_index_pages(config)
        _print(
            {
                "status": "maintained",
                "updated_files": [str(p.relative_to(config.root)) for p in updated],
            },
            args.json,
        )
        return
    if args.command == "validate-index":
        errors = validate_index_links(config)
        _print(
            {
                "status": "valid" if not errors else "invalid",
                "errors": errors,
            },
            args.json,
        )
        raise SystemExit(1 if errors else 0)
    if args.command == "refresh-index":
        _print(refresh_index(config), args.json)
        raise SystemExit(0 if not refresh_index(config).get("errors") else 1)
    parser.error(f"Unsupported command: {args.command}")


def _print(payload, as_json: bool, search_mode: bool = False) -> None:
    if as_json or not search_mode:
        print(json.dumps(payload, indent=2))
        return
    if not payload:
        print("No results.")
        return
    for result in payload:
        print(f"{result['score']:.1f}  {result['title']}  [{result['page_id']}]")
        print(f"  {result['path']}")
        print(f"  matches: {', '.join(result['matches'])}")
        print(f"  {result['snippet']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="audiagentic-knowledge", description="AUDiaGentic knowledge capability CLI v7"
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root that contains the configured knowledge contract",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional config path override. Defaults to .audiagentic/knowledge/config.yml or AUDIAGENTIC_KNOWLEDGE_CONFIG.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common_json_commands = [
        "validate",
        "status",
        "show-hooks",
        "show-event-adapters",
        "show-importer-registry",
        "show-action-registry",
        "show-event-action-registry",
        "show-llm-registry",
        "show-navigation",
        "record-event-baseline",
        "list-profiles",
        "show-execution-registry",
        "show-install-profiles",
        "show-capability-contract",
        "doctor",
        "proposal-summary",
    ]
    for name in common_json_commands:
        p = sub.add_parser(name)
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("bootstrap")
    p.add_argument("--target", default=".")
    p.add_argument("--knowledge-root", default="knowledge")
    p.add_argument("--config-relpath", default=".audiagentic/knowledge/config.yml")
    p.add_argument("--force", action="store_true")
    p.add_argument("--capability-profile", default="deterministic-minimal")
    p.add_argument("--host-profile", default="mcp-stdio")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("answer-question")
    p.add_argument("question")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--mode", choices=["blocking", "async"])
    p.add_argument("--allow-llm", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("draft-sync-proposal")
    p.add_argument("--page-id")
    p.add_argument("--mode", choices=["blocking", "async"])
    p.add_argument("--allow-llm", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("bootstrap-project-knowledge")
    p.add_argument("--manifest")
    p.add_argument("--mode", choices=["blocking", "async"])
    p.add_argument("--allow-llm", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("submit-profile-job")
    p.add_argument("task_name")
    p.add_argument("--payload", default="{}")
    p.add_argument("--mode", choices=["blocking", "async"], default="async")
    p.add_argument("--allow-llm", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("get-job-status")
    p.add_argument("job_id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("get-job-result")
    p.add_argument("job_id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("prune-events")
    p.add_argument("--max-events", type=int, default=1000)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("navigate")
    p.add_argument("goal")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("list-actions")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("run-action")
    p.add_argument("action_id")
    p.add_argument(
        "--arguments", default="{}", help="JSON object with runtime arguments for the action"
    )
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("get-page")
    p.add_argument("page_id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("apply-patch")
    p.add_argument("patch")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("scan-drift")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("record-sync")
    p.add_argument("page_id", nargs="*")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("mark-stale")
    p.add_argument("page_id", nargs="+")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("clear-stale")
    p.add_argument("page_id", nargs="+")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("generate-sync-proposals")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("apply-proposals")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("list-proposals")
    p.add_argument("--status")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("get-proposal")
    p.add_argument("proposal_id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("accept-proposal")
    p.add_argument("proposal_id")
    p.add_argument("--note")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("reject-proposal")
    p.add_argument("proposal_id")
    p.add_argument("--note")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("apply-proposal")
    p.add_argument("proposal_id")
    p.add_argument("--note")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("cleanup-lifecycle")
    p.add_argument("--job-retention-days", type=int)
    p.add_argument("--proposal-retention-days", type=int)
    p.add_argument("--archive-retention-days", type=int)
    p.add_argument("--keep-pending-proposals", action="store_true")
    p.add_argument("--keep-duplicate-proposals", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("evaluate-source")
    p.add_argument("relative_path")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("scan-events")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("process-events")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("seed-from-manifest")
    p.add_argument("manifest")
    p.add_argument("--record-sync", action="store_true")
    p.add_argument("--update-existing", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("scaffold-page")
    p.add_argument("page_id")
    p.add_argument("title")
    p.add_argument("page_type")
    p.add_argument("summary")
    p.add_argument("--owner", action="append", required=True)
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--related", action="append", default=[])
    p.add_argument("--source-refs", default="[]")
    p.add_argument("--update-existing", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("maintain-index")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("validate-index")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("refresh-index")
    p.add_argument("--json", action="store_true")
    return parser
