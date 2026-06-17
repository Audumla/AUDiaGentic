"""Lifecycle CLI stub."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from audiagentic.foundation.contracts.errors import AudiaGenticError, to_error_envelope


def _plan_payload() -> dict:
    return {
        "contract-version": "v1",
        "mode": "plan",
        "state-classification": "unknown",
        "operations": ["scan-project"],
        "warnings": [],
        "blocking-errors": [],
    }


def _apply_payload() -> dict:
    return {
        "contract-version": "v1",
        "mode": "apply",
        "status": "success",
        "completed-operations": ["noop"],
        "warnings": [],
    }


def _validate_payload() -> dict:
    return {
        "contract-version": "v1",
        "status": "pass",
        "checks": [{"check-id": "stub", "result": "pass"}],
        "warnings": [],
    }


def run_stub(mode: str, project_root: Path) -> dict:
    if mode == "plan":
        return _plan_payload()
    if mode == "apply":
        return _apply_payload()
    if mode == "validate":
        return _validate_payload()
    raise AudiaGenticError(
        code="VAL-STUB-001",
        kind="lifecycle",
        message=f"unsupported mode: {mode}",
        details={"mode": mode},
    )


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Lifecycle CLI stub")
    parser.add_argument("--mode", required=True, choices=["plan", "apply", "validate"])
    parser.add_argument("--project-root", required=True)
    args = parser.parse_args(argv)
    try:
        payload = run_stub(args.mode, Path(args.project_root))
    except AudiaGenticError as exc:
        print(json.dumps(to_error_envelope(exc), indent=2, sort_keys=True))
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
