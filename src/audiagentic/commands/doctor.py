"""``audiagentic doctor`` and ``audiagentic setup`` (CFG08).

Adapter only. Checks live with their owning components and are discovered by
``foundation.lifecycle.doctor``. ``doctor`` is read-only. ``setup`` is
idempotent: it creates only the missing user settings file and, for each
harness named with ``harness ID[,ID...]``, registers the worktree-scoped MCP
servers at that harness's user scope (``dry-run`` only reports); then it runs
doctor.
Exit codes: 0 no failures (warnings allowed), 2 at least one failed check.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

EXIT_FAILED = 2
_MARK = {"ok": "ok  ", "warn": "WARN", "fail": "FAIL"}


def add_doctor_parsers(subparsers: Any) -> None:
    doctor = subparsers.add_parser("doctor", help="Check configuration and environment (read-only)")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    setup = subparsers.add_parser(
        "setup", help="Create missing user configuration, register user-scope MCP, then run doctor")
    setup.add_argument("--json", action="store_true", dest="as_json")
    setup.add_argument("clauses", nargs="*", metavar="harness ID[,ID...] | dry-run")


def run_doctor_command(args: argparse.Namespace) -> int:
    from pathlib import Path

    from audiagentic.foundation.lifecycle.doctor import FAIL, DoctorContext, run_checks

    created: list[str] = []
    registrations: list[dict] = []
    if args.command == "setup":
        harness_ids, dry_run = _setup_clauses(args.clauses)
        if not dry_run:
            created = _ensure_user_settings()
        if harness_ids:
            from audiagentic.components.project import project_api

            registrations = project_api.setup_user_mcp(harness_ids, dry_run=dry_run)
    results = run_checks(DoctorContext(Path(args.project) if args.project else None))
    failed = any(result.status == FAIL for result in results)
    if args.as_json:
        payload: dict[str, Any] = {"ok": not failed, "checks": [result.to_dict() for result in results]}
        if args.command == "setup":
            payload["created"] = created
            payload["mcp"] = registrations
        print(json.dumps(payload, indent=2))
    else:
        for path in created:
            print(f"created {path}")
        for row in registrations:
            print(_registration_line(row))
        for result in results:
            print(f"[{_MARK.get(result.status, result.status)}] {result.check}: {result.message}")
            if result.fix and result.status != "ok":
                print(f"         fix: {result.fix}")
    return EXIT_FAILED if failed or any(not row.get("ok", True) for row in registrations) else 0


def _setup_clauses(clauses: list[str]) -> tuple[list[str], bool]:
    """``harness ID[,ID...]`` and ``dry-run``, each at most once."""
    harness_ids: list[str] = []
    dry_run = False
    rest = list(clauses)
    while rest:
        key = rest.pop(0)
        if key == "dry-run" and not dry_run:
            dry_run = True
        elif key == "harness" and not harness_ids and rest:
            harness_ids = list(dict.fromkeys(value.strip() for value in rest.pop(0).split(",")))
            if not all(harness_ids):
                raise SystemExit("setup: harness list contains an empty ID")
        else:
            raise SystemExit(f"setup: unknown or repeated clause: {key}; expected harness ID[,ID...] or dry-run")
    return harness_ids, dry_run


def _registration_line(row: dict) -> str:
    target = f"{row['provider_id']} user MCP ({row['target']})"
    if "entries" in row:
        return f"{target}: " + ", ".join(f"{entry['name']} {entry['state']}" for entry in row["entries"])
    if not row["ok"]:
        names = ", ".join(item["desired_name"] for item in row["collisions"])
        return (f"{target}: not registered; {names} already exist there and were not registered by setup. "
                "Remove them from that harness's user MCP configuration if they are yours to replace, "
                "then re-run setup")
    changed = ", ".join(row["updated"] + [f"removed {name}" for name in row["removed"]])
    return f"{target}: {changed or 'already up to date'}"


def _ensure_user_settings() -> list[str]:
    from audiagentic.foundation.config.settings import SETTINGS_FILE
    from audiagentic.foundation.paths.home import user_config_dir

    path = user_config_dir() / SETTINGS_FILE
    if path.exists():
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# User settings: override only what you change. See 'audiagentic config show --origin'.\n"
                    "schema_version: 1\n", encoding="utf-8")
    return [str(path)]
