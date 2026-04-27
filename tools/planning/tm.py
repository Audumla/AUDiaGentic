#!/usr/bin/env python3
"""Planning task manager CLI for AUDiaGentic projects.

Usage (from any directory):
    python tools/tm.py --root <project-root> validate
    python tools/tm.py validate          # defaults to project root detection
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Bootstrap: make tools.lib importable, then use robust multi-fallback root discovery.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.lib.repo_paths import REPO_ROOT, SRC_ROOT


def _find_project_root() -> Path:
    """Walk up from cwd to find the nearest directory containing .audiagentic/planning/."""
    cwd = Path.cwd()
    for p in [cwd, *cwd.parents]:
        if (p / ".audiagentic" / "planning").exists():
            return p
    # Fallback: script's grandparent (tools/../)
    return Path(__file__).resolve().parents[1]


def _setup_sys_path(root: Path) -> None:
    src = root / "src"
    for p in (str(root), str(src)):
        if p not in sys.path:
            sys.path.insert(0, p)


def print_json(data):
    import io
    import sys

    # Force UTF-8 encoding for stdout
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print(json.dumps(data, indent=2, ensure_ascii=False))


def _propagation_log_path(root: Path) -> Path:
    return root / ".audiagentic" / "planning" / "meta" / "propagation_log.json"


def _append_propagation_audit_log(root: Path, entries: list[dict]) -> Path:
    path = _propagation_log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, list):
            existing = []
    else:
        existing = []
    existing.extend(entries)
    path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _run_audit(api, root: Path, *, auto_fix: bool, verbose: bool) -> tuple[dict, int]:
    auditable_kinds = set(api.config.all_kinds())
    findings = []
    log_entries = []

    for item in api._scan():
        if item.kind not in auditable_kinds or api.config.is_soft_deleted(item.data):
            continue
        errors = api._propagation_engine.validate_hierarchy(item.data["id"])
        if not errors:
            continue

        finding = {
            "id": item.data["id"],
            "kind": item.kind,
            "state": item.data.get("state"),
            "errors": errors,
        }

        if auto_fix:
            healing = api._propagation_engine.heal_hierarchy(item.data["id"], auto_fix=True)
            finding["fixes"] = healing.get("fixes", [])
            for fix in finding["fixes"]:
                if fix.get("can_auto_fix") and not fix.get("applied"):
                    api._propagation_engine._apply_fix(fix)  # noqa: SLF001 - CLI repair path
                    fix["applied"] = True
            for fix in healing.get("fixes", []):
                if fix.get("applied"):
                    log_entries.append(
                        {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "source": "planning.audit",
                            "fixed_by_audit": True,
                            "item_id": item.data["id"],
                            "kind": item.kind,
                            "target_id": fix.get("target_id"),
                            "target_state": fix.get("target_state"),
                            "suggestion": fix.get("suggestion"),
                            "error": fix.get("error"),
                            "status": "fixed",
                        }
                    )
        elif verbose:
            finding["fixes"] = [
                api._propagation_engine._suggest_fix(error)  # noqa: SLF001 - CLI introspection
                for error in errors
            ]

        findings.append(finding)

    log_path = None
    if log_entries:
        log_path = _append_propagation_audit_log(root, log_entries)

    remaining = 0
    for finding in findings:
        fixes = finding.get("fixes", [])
        if auto_fix and fixes and all(fix.get("applied") for fix in fixes if fix.get("can_auto_fix")):
            post_errors = api._propagation_engine.validate_hierarchy(finding["id"])
            finding["remaining_errors"] = post_errors
            remaining += len(post_errors)
        else:
            remaining += len(finding["errors"])

    payload = {
        "ok": remaining == 0,
        "items_scanned": len([i for i in api._scan() if i.kind in auditable_kinds and not api.config.is_soft_deleted(i.data)]),
        "findings": findings,
        "issues_found": sum(len(f["errors"]) for f in findings),
        "remaining_issues": remaining,
        "fixes_applied": len(log_entries),
        "log_path": str(log_path.relative_to(root)) if log_path else None,
    }
    exit_code = 0 if payload["ok"] else 1
    return payload, exit_code


def main():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--root", default=None)
    known, _ = pre.parse_known_args()

    root = Path(known.root).resolve() if known.root else _find_project_root()
    _setup_sys_path(root)

    from audiagentic.planning.app.api import PlanningAPI

    api = PlanningAPI(root)

    p = argparse.ArgumentParser(prog="tm")
    p.add_argument("--root", default=None, help="Project root (default: auto-detect from cwd)")
    sp = p.add_subparsers(dest="cmd", required=True)
    p_new = sp.add_parser("new")
    p_new.add_argument("kind")
    p_new.add_argument("--label", required=True)
    p_new.add_argument("--summary", required=True)
    p_new.add_argument("--domain")
    p_new.add_argument("--workflow")
    p_new.add_argument(
        "--ref",
        action="append",
        default=[],
        help="Creation ref as input=value. Repeat for list refs.",
    )
    p_new.add_argument(
        "--profile",
        default=None,
        help="Profile name for request defaults and stack topology (e.g. feature, issue, direct, full). Defaults to project default.",
    )
    p_new.add_argument(
        "--guidance",
        help="Guidance level for content depth (light, standard, deep). Defaults to project default.",
    )
    p_new.add_argument("--understanding", dest="current_understanding")
    p_new.add_argument("--question", action="append", dest="open_questions")
    p_new.add_argument(
        "--source",
        required=True,
        help="Source of request (e.g. user, claude, jira, slack)",
    )
    p_new.add_argument("--context")
    p_up = sp.add_parser("update")
    p_up.add_argument("id")
    p_up.add_argument("--label")
    p_up.add_argument("--summary")
    p_up.add_argument("--append")
    p_mv = sp.add_parser("move")
    p_mv.add_argument("id")
    p_mv.add_argument("--domain", required=True)
    p_state = sp.add_parser("state")
    p_state.add_argument("id")
    p_state.add_argument("state")
    p_del = sp.add_parser("delete")
    p_del.add_argument("id")
    p_del.add_argument("--hard", action="store_true")
    p_del.add_argument("--reason")
    p_rel = sp.add_parser("relink")
    p_rel.add_argument("src")
    p_rel.add_argument("field")
    p_rel.add_argument("dst")
    p_rel.add_argument("--seq", type=int)
    p_rel.add_argument("--display")
    p_action = sp.add_parser("action")
    p_action.add_argument("action")
    p_action.add_argument(
        "--context",
        required=True,
        help="JSON object passed to the configured workflow action",
    )
    sp.add_parser("validate")
    p_ls = sp.add_parser("list")
    p_ls.add_argument("kind", nargs="?")
    p_ls.add_argument("--include-deleted", action="store_true")
    p_ls.add_argument("--include-archived", action="store_true")
    p_ls.add_argument("--include-superseded", action="store_true")
    p_show = sp.add_parser("show")
    p_show.add_argument("id")
    sp.add_parser("status")
    sp.add_parser("trace")
    p_ext = sp.add_parser("extract")
    p_ext.add_argument("id")
    p_ext.add_argument("--with-related", action="store_true")
    p_ext.add_argument("--with-resources", action="store_true")
    p_files = sp.add_parser("files")
    p_files.add_argument("id")
    p_owner = sp.add_parser("owner")
    p_owner.add_argument("path_fragment")
    sp.add_parser("index")
    sp.add_parser("reconcile")
    sp.add_parser("rebaseline")
    p_audit = sp.add_parser("audit")
    p_audit.add_argument("--fix", action="store_true")
    p_audit.add_argument("--verbose", action="store_true")
    p_dump = sp.add_parser("dump")
    p_dump.add_argument("--output", help="Output directory (default: stdout as JSON)")
    p_dump.add_argument("--format", choices=["json", "yaml"], default="json", help="Output format")
    p_claim = sp.add_parser("claim")
    p_claim.add_argument("kind")
    p_claim.add_argument("id")
    p_claim.add_argument("--holder", required=True)
    p_claim.add_argument("--ttl", type=int)
    p_unclaim = sp.add_parser("unclaim")
    p_unclaim.add_argument("id")
    p_claims = sp.add_parser("claims")
    p_claims.add_argument("kind", nargs="?")
    p_events = sp.add_parser("events")
    p_events.add_argument("--tail", type=int, default=20)
    p_next = sp.add_parser("next")
    p_next.add_argument("kind", nargs="?")
    p_next.add_argument("--state")
    p_next.add_argument("--domain")
    p_stds = sp.add_parser("standards")
    p_stds.add_argument("id")
    sp.add_parser("hooks")
    sp.add_parser(
        "sync-counters",
        help="Seed ID counters from existing docs (run once after install)",
    )
    args = p.parse_args()

    if args.cmd == "new":
        refs: dict[str, object] = {}
        for entry in args.ref:
            if "=" not in entry:
                raise SystemExit("--ref must be input=value")
            key, value = entry.split("=", 1)
            if key in refs:
                existing = refs[key]
                refs[key] = [*existing, value] if isinstance(existing, list) else [existing, value]
            else:
                refs[key] = value
        item = api.new(
            args.kind,
            label=args.label,
            summary=args.summary,
            domain=args.domain,
            workflow=args.workflow,
            refs=refs,
            profile=args.profile,
            guidance=args.guidance,
            current_understanding=args.current_understanding,
            open_questions=args.open_questions,
            source=args.source,
            context=args.context,
        )
        print_json({"id": item.data["id"], "path": str(item.path.relative_to(root))})
    elif args.cmd == "update":
        item = api.update(args.id, label=args.label, summary=args.summary, body_append=args.append)
        print_json({"id": item.data["id"], "path": str(item.path.relative_to(root))})
    elif args.cmd == "move":
        item = api.move(args.id, args.domain)
        print_json({"id": item.data["id"], "path": str(item.path.relative_to(root))})
    elif args.cmd == "state":
        item = api.state(args.id, args.state)
        print_json({"id": item.data["id"], "state": item.data["state"]})
    elif args.cmd == "delete":
        print_json(api.delete(args.id, hard=args.hard, reason=args.reason))
    elif args.cmd == "relink":
        item = api.relink(args.src, args.field, args.dst, args.seq, args.display)
        print_json({"id": item.data["id"], "field": args.field})
    elif args.cmd == "action":
        context = json.loads(args.context)
        result = api.run_workflow_action(args.action, context)
        print_json(
            {
                key: {"id": item.data["id"], "path": str(item.path.relative_to(root))}
                for key, item in result.items()
            }
        )
    elif args.cmd == "validate":
        errs = api.validate()
        print_json({"ok": not errs, "errors": errs})
        raise SystemExit(1 if errs else 0)
    elif args.cmd == "list":
        items = api._scan()
        if args.kind:
            items = [i for i in items if i.kind == args.kind]
        if not args.include_deleted:
            items = [i for i in items if not api.config.is_soft_deleted(i.data)]
        if not args.include_archived:
            archive_state = api.config.lifecycle_action_state("archive")
            items = [i for i in items if i.data.get("state") != archive_state]
        if not args.include_superseded:
            supersede_state = api.config.lifecycle_action_state("supersede")
            items = [i for i in items if i.data.get("state") != supersede_state]
        print_json(
            [
                {
                    "id": i.data["id"],
                    "kind": i.kind,
                    "label": i.data["label"],
                    "state": i.data["state"],
                    "terminal": api.config.state_in_set(
                        i.kind, i.data.get("state"), "terminal", i.data.get("workflow")
                    ),
                }
                for i in items
            ]
        )
    elif args.cmd == "show":
        print_json(api.extracts.show(args.id))
    elif args.cmd == "status":
        items = api._scan()
        out = {}
        for i in items:
            out.setdefault(i.kind, {})
            out[i.kind].setdefault(i.data["state"], 0)
            out[i.kind][i.data["state"]] += 1
        print_json(out)
    elif args.cmd == "trace":
        pth = root / ".audiagentic/planning/indexes/trace.json"
        if not pth.exists():
            api.index()
        print(pth.read_text(encoding="utf-8"))
    elif args.cmd == "extract":
        print_json(api.extracts.extract(args.id, args.with_related, args.with_resources))
    elif args.cmd == "files":
        print_json(api.extracts.extract(args.id, with_resources=True).get("attachments", []))
    elif args.cmd == "owner":
        print_json(api.extracts.owner(args.path_fragment))
    elif args.cmd == "index":
        api.index()
        print_json({"ok": True})
    elif args.cmd == "reconcile":
        print_json(api.reconcile())
    elif args.cmd == "rebaseline":
        print_json(api.rebaseline())
    elif args.cmd == "audit":
        payload, exit_code = _run_audit(api, root, auto_fix=args.fix, verbose=args.verbose)
        print_json(payload)
        raise SystemExit(exit_code)
    elif args.cmd == "dump":
        print_json(api.dump_all(args.output, args.format))
    elif args.cmd == "claim":
        print_json(api.claim(args.kind, args.id, args.holder, args.ttl))
    elif args.cmd == "unclaim":
        print_json({"ok": api.unclaim(args.id)})
    elif args.cmd == "claims":
        print_json(api.claims(args.kind))
    elif args.cmd == "events":
        p2 = root / ".audiagentic/planning/events/events.jsonl"
        if not p2.exists():
            print_json([])
        else:
            lines = p2.read_text(encoding="utf-8").strip().splitlines()[-args.tail :]
            print_json([json.loads(x) for x in lines if x.strip()])
    elif args.cmd == "next":
        defaults = api.config.queue_defaults()
        print_json(
            api.next_items(
                args.kind or defaults["kind"],
                args.state or defaults["state"],
                args.domain,
            )
        )
    elif args.cmd == "standards":
        print_json(api.effective_refs(args.id))
    elif args.cmd == "hooks":
        print_json(api.hooks_info())
    elif args.cmd == "sync-counters":
        api.sync_id_counters()
        print_json({"ok": True, "root": str(root)})


if __name__ == "__main__":
    main()
