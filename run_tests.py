#!/usr/bin/env python
"""Single-entry test runner: unit + integration + docker tests."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_AI_TESTER = str(ROOT / "tests/unit/runtime/test_ai_tester.py")


def run(cmd: list[str], label: str, env_add: dict[str, str] | None = None) -> int:
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"{'='*70}")
    env = {**os.environ, **(env_add or {})}
    result = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=False)
    return result.returncode


def main() -> int:
    ignore = ["--ignore", SKIP_AI_TESTER]
    rc = 0

    # Phase 1: unit + integration (no docker, no real cli)
    rc |= run(
        [sys.executable, "-m", "pytest", "tests/unit", "tests/integration"]
        + ignore
        + ["-v", "--tb=short", "-q", "--no-header"],
        "PHASE 1: Unit + Integration (no docker, no real-cli)",
    )

    # Phase 2: all tests including docker and real-cli
    rc |= run(
        [sys.executable, "-m", "pytest", "tests/unit", "tests/integration"]
        + ignore
        + ["-v", "--tb=short", "-q", "--no-header"],
        "PHASE 2: All tests (docker + real-cli enabled)",
        {"AUDIAGENTIC_DOCKER_TESTS": "1", "AUDIAGENTIC_REAL_PROVIDER_CLI_TESTS": "1"},
    )

    print(f"\n{'='*70}")
    if rc == 0:
        print("  ALL PHASES PASSED")
    else:
        print(f"  DONE (exit code {rc})")
    print(f"{'='*70}\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
