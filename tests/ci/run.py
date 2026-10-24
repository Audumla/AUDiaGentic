"""Run fast gates or an audited full-suite lane with timing/JUnit artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from tests.ci.policy import BROWSER_MODULES, CRITICAL, FULL_ROOTS, HERMETIC, fast_paths, partition

ROOT = Path(__file__).resolve().parents[2]


def command(args: list[str], *, env: dict[str, str]) -> int:
    print("+", " ".join(args), flush=True)
    return subprocess.run(args, cwd=ROOT, env=env, check=False).returncode


def changed_paths(base: str) -> list[str]:
    if not base or set(base) == {"0"}:
        return []
    if not re.fullmatch(r"[a-fA-F0-9]{40,64}", base):
        raise ValueError("base must be an immutable commit SHA")
    result = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD", "--"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=["fast", "full"], required=True)
    parser.add_argument(
        "--lane", default="all", choices=["all", "inventory", "serial", "browser", "shard"]
    )
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--base", default="")
    parser.add_argument("--results", default=".ci-results")
    parser.add_argument("--plan", default=None)
    args = parser.parse_args()
    if args.shards < 1 or not 0 <= args.index < args.shards or args.workers < 1:
        parser.error("invalid shard/worker bounds")
    output = (ROOT / args.results).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("CI evidence directory must be empty; never reuse an earlier run's proof")
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["AUDIAGENTIC_REPO_ROOT"] = str(ROOT)
    env["AUDIAGENTIC_SERIAL_PHASE"] = "1"  # collect the complete canonical universe
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    env["CI_SOURCE_SHA"] = sha.stdout.strip() or os.environ.get("CI_SOURCE_SHA", "unknown")
    roots = fast_paths(ROOT, changed_paths(args.base)) if args.tier == "fast" else list(FULL_ROOTS)
    mark = HERMETIC + (
        " and not slow and not long_running and not requires_network" if args.tier == "fast" else ""
    )
    ignore = (
        [part for module in BROWSER_MODULES for part in ("--ignore", module)]
        if args.tier == "fast"
        else []
    )
    pytest_args = [sys.executable, "-m", "pytest", "-p", "tests.ci.evidence"]
    started = time.monotonic()
    timings: dict[str, float] = {}
    if args.plan:
        if args.tier != "full":
            raise ValueError("precomputed plans are only valid for full lanes")
        collection = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        if collection.get("source_sha") != env["CI_SOURCE_SHA"]:
            raise ValueError("coverage plan belongs to a different commit")
    else:
        collect_file = output / "collection.json"
        rc = command(
            [
                *pytest_args,
                *roots,
                *ignore,
                "-m",
                mark,
                "--collect-only",
                "-q",
                "--ci-evidence",
                str(collect_file),
            ],
            env=env,
        )
        if rc:
            return rc
        collection = json.loads(collect_file.read_text(encoding="utf-8"))
    timings["inventory"] = round(time.monotonic() - started, 3)
    lanes = partition(collection["nodes"], args.shards)
    if args.tier == "fast":
        actual_modules = {node["nodeid"].split("::", 1)[0] for node in collection["nodes"]}
        for required in CRITICAL:
            if required.endswith(".py") and required not in actual_modules:
                raise ValueError(f"mandatory fast tests were filtered out: {required}")
    if args.plan and lanes != collection.get("lanes"):
        raise ValueError("coverage plan partition does not match the requested policy")
    role = f"shard-{args.index}" if args.lane == "shard" else args.lane
    plan = {
        "schema": 1,
        "source_sha": env["CI_SOURCE_SHA"],
        "tier": args.tier,
        "role": role,
        "nodes": collection["nodes"],
        "lanes": lanes,
    }
    (output / "plan.json").write_text(json.dumps(plan, sort_keys=True), encoding="utf-8")
    if args.lane == "inventory":
        return 0
    chosen = (
        list(lanes)
        if args.lane == "all"
        else [f"shard-{args.index}" if args.lane == "shard" else args.lane]
    )
    if args.lane == "all" and args.tier == "fast":
        chosen.remove("browser")
    final = 0
    for lane in chosen:
        modules = lanes[lane]
        if not modules:
            if lane.startswith("shard-"):
                raise ValueError(f"empty required shard: {lane}")
            continue  # serial/browser may legitimately be absent in a targeted selection
        if lane == "browser":
            from playwright.sync_api import sync_playwright

            # Existing browser tests skip on a missing executable. CI must not
            # report successful browser coverage when no browser actually ran.
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                browser.close()
        evidence = output / f"{lane}.json"
        lane_started = time.monotonic()
        flags = ["-n", str(args.workers), "--dist", "loadfile"] if lane.startswith("shard-") else []
        test_env = dict(env)
        if flags:
            test_env.pop("AUDIAGENTIC_SERIAL_PHASE", None)
        rc = command(
            [
                *pytest_args,
                *modules,
                "-m",
                mark,
                *flags,
                "--durations=30",
                "--junitxml",
                str(output / f"{lane}.xml"),
                "--ci-evidence",
                str(evidence),
            ],
            env=test_env,
        )
        timings[lane] = round(time.monotonic() - lane_started, 3)
        final = final or rc
        report_files = list(output.glob(f"{lane}-gw*.json")) or [evidence]
        reports = [
            json.loads(path.read_text(encoding="utf-8")) for path in report_files if path.exists()
        ]
        executed = {node for report in reports for node in report["results"]}
        duplicates = {
            node
            for node, count in Counter(
                node for report in reports for node in report["results"]
            ).items()
            if count != 1
        }
        if not any(
            result.get("call", {}).get("outcome") == "passed"
            for report in reports
            for result in report["results"].values()
        ):
            final = final or 1
        expected = {
            node["nodeid"]
            for node in collection["nodes"]
            if node["nodeid"].split("::", 1)[0] in modules
        }
        if expected != executed or duplicates:
            print(
                f"coverage mismatch {lane}: missing={len(expected - executed)} unexpected={len(executed - expected)}",
                file=sys.stderr,
            )
            final = final or 1
    (output / "summary.json").write_text(
        json.dumps(
            {
                "source_sha": env["CI_SOURCE_SHA"],
                "seconds": round(time.monotonic() - started, 3),
                "exitstatus": final,
                "phase_seconds": timings,
            }
        ),
        encoding="utf-8",
    )
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            summary.write(f"\nCI {args.tier}/{role}: {env['CI_SOURCE_SHA']}\n\n")
            for phase, seconds in timings.items():
                summary.write(f"- {phase}: {seconds:.3f}s\n")
            summary.write(f"\nExit status: {final}\n")
    return final


if __name__ == "__main__":
    raise SystemExit(main())
