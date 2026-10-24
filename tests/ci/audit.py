"""Verify full-lane artifact provenance and exact collection/execution parity."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def audit(root: Path, sha: str, shards: int) -> dict:
    plans = [json.loads(path.read_text(encoding="utf-8")) for path in root.rglob("plan.json")]
    expected_roles = {
        "inventory",
        "serial",
        "browser",
        *{f"shard-{index}" for index in range(shards)},
    }
    roles = [plan["role"] for plan in plans]
    if set(roles) != expected_roles or len(roles) != len(set(roles)):
        raise ValueError("missing or duplicated full-suite lane evidence")
    if any(plan["source_sha"] != sha for plan in plans):
        raise ValueError("full-suite evidence mixes source commits")
    baseline = next(plan for plan in plans if plan["role"] == "inventory")
    if any(
        plan["nodes"] != baseline["nodes"] or plan["lanes"] != baseline["lanes"] for plan in plans
    ):
        raise ValueError("full-suite lanes do not share the same canonical collection")
    counts = Counter()
    for plan_path in root.rglob("plan.json"):
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        role = plan["role"]
        if role == "inventory":
            continue
        report_files = list(plan_path.parent.glob(f"{role}-gw*.json")) or [
            plan_path.parent / f"{role}.json"
        ]
        executed = Counter()
        for report_path in report_files:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report["source_sha"] != sha or report["exitstatus"] != 0:
                raise ValueError(f"failed or foreign lane: {role}")
            executed.update(report["results"].keys())
        expected = {
            node["nodeid"]
            for node in baseline["nodes"]
            if node["nodeid"].split("::", 1)[0] in baseline["lanes"][role]
        }
        if set(executed) != expected or any(count != 1 for count in executed.values()):
            raise ValueError(f"lane did not execute exactly its assigned tests: {role}")
        counts.update(executed)
    if set(counts) != {node["nodeid"] for node in baseline["nodes"]} or any(
        count != 1 for count in counts.values()
    ):
        raise ValueError("full run omitted or duplicated tests")
    return {"source_sha": sha, "tests_accounted_for": len(counts), "lanes": len(expected_roles) - 1}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--shards", type=int, default=4)
    args = parser.parse_args()
    print(json.dumps(audit(args.directory, args.sha, args.shards), sort_keys=True))


if __name__ == "__main__":
    main()
