"""Run the unit suite in partitions that are each internally parallel-safe.

Why partitions rather than one `pytest -n auto`:

`tests/unit/foundation` resets global registries before every one of its tests
(autouse fixture in its conftest). Any test that reads those registries and
lands on the same xdist worker sees the wrecked state. Worker packing varies
per run, so a single parallel command fails a different handful of tests each
time. Splitting foundation into its own worker pool removes the interference
without giving up parallelism, because workers are separate processes.

Tests marked `no_parallel` are held out of every parallel phase (the root
conftest deselects them and says so) and run afterwards in a serial phase.
Foundation's `no_parallel` tests get their own serial phase because some of
them register components against synthetic config trees, which poisons the
process for anything that reads a real registry.

Usage:
    python tools/run_unit_suite.py             # all phases
    python tools/run_unit_suite.py -k pattern  # extra args go to every phase
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

FOUNDATION = "tests/unit/foundation"
UNIT = "tests/unit"

#: (label, pytest args, extra env)
PHASES: list[tuple[str, list[str], dict[str, str]]] = [
    (
        "parallel: everything except foundation",
        [UNIT, f"--ignore={FOUNDATION}", "-n", "auto", "--dist", "loadfile"],
        {},
    ),
    (
        "parallel: foundation",
        [FOUNDATION, "-n", "auto", "--dist", "loadfile"],
        {},
    ),
    (
        "serial: no_parallel, except foundation",
        [UNIT, f"--ignore={FOUNDATION}", "-m", "no_parallel"],
        {"AUDIAGENTIC_SERIAL_PHASE": "1"},
    ),
]

#: Files whose no_parallel tests need a process of their own, not merely a
#: serial phase. These register components against synthetic config trees, which
#: replaces the live registries and error catalogue for the rest of the process
#: — so they poison each other if they share one.
ISOLATED_FILES = [
    f"{FOUNDATION}/test_component_profiles.py",
    f"{FOUNDATION}/test_component_status_hooks.py",
]

for _path in ISOLATED_FILES:
    PHASES.append(
        (
            f"serial (own process): {_path}",
            [_path, "-m", "no_parallel"],
            {"AUDIAGENTIC_SERIAL_PHASE": "1"},
        )
    )


def main(argv: list[str]) -> int:
    extra = argv[1:]
    failed: list[str] = []
    started = time.monotonic()

    for label, args, env_extra in PHASES:
        print(f"\n{'=' * 70}\n{label}\n{'=' * 70}", flush=True)
        env = {**os.environ, **env_extra}
        phase_start = time.monotonic()
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *args, *extra], env=env
        )
        elapsed = time.monotonic() - phase_start
        print(f"-- {label}: exit {result.returncode} in {elapsed:.1f}s", flush=True)
        # Exit code 5 is "no tests collected", which is fine for a filtered
        # phase (e.g. `-k` matched nothing here) but not for an unfiltered run.
        if result.returncode not in (0, *( (5,) if extra else () )):
            failed.append(label)

    total = time.monotonic() - started
    print(f"\n{'=' * 70}")
    if failed:
        print(f"FAILED phases ({len(failed)}) in {total:.1f}s:")
        for label in failed:
            print(f"  - {label}")
        return 1
    print(f"All phases passed in {total:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
