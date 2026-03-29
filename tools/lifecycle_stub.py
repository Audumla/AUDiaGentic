"""Lifecycle CLI stub."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from audiagentic.contracts.errors import AudiaGenticError, to_error_envelope
from audiagentic.lifecycle.checkpoints import write_checkpoint


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
        "checkpoint-dir": ".audiagentic/runtime/lifecycle/checkpoints",
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
        payload = _plan_payload()
        write_checkpoint(project_root, "detected", payload)
        return payload
    if mode == "apply":
        payload = _apply_payload()
        write_checkpoint(project_root, "planned", payload)
        write_checkpoint(project_root, "pre-destructive", payload)
        return payload
    if mode == "validate":
        return _validate_payload()
    raise AudiaGenticError(
        code="LFC-VALIDATION-001",
        kind="validation",
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
