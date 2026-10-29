"""``audiagentic doctor`` and ``audiagentic setup`` (CFG08).

Adapter only. Checks live with their owning components and are discovered by
``foundation.lifecycle.doctor``. ``doctor`` is read-only. ``setup`` is
idempotent: it creates only the missing user settings file, then runs doctor.
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
    setup = subparsers.add_parser("setup", help="Create missing user configuration, then run doctor")
    setup.add_argument("--json", action="store_true", dest="as_json")


def run_doctor_command(args: argparse.Namespace) -> int:
    from pathlib import Path

    from audiagentic.foundation.lifecycle.doctor import FAIL, DoctorContext, run_checks

    created: list[str] = []
    if args.command == "setup":
        created = _ensure_user_settings()
    results = run_checks(DoctorContext(Path(args.project) if args.project else None))
    failed = any(result.status == FAIL for result in results)
    if args.as_json:
        payload: dict[str, Any] = {"ok": not failed, "checks": [result.to_dict() for result in results]}
        if args.command == "setup":
            payload["created"] = created
        print(json.dumps(payload, indent=2))
    else:
        for path in created:
            print(f"created {path}")
        for result in results:
            print(f"[{_MARK.get(result.status, result.status)}] {result.check}: {result.message}")
            if result.fix and result.status != "ok":
                print(f"         fix: {result.fix}")
    return EXIT_FAILED if failed else 0


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
