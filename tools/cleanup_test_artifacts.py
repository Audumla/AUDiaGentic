#!/usr/bin/env python
"""
Cleanup test artifacts from planning and knowledge systems.

Removes soft-deleted test artifacts and optionally resets counters.
Test artifacts are identified by 'test-' prefix in their labels.

Usage:
    python tools/cleanup_test_artifacts.py [--dry-run] [--reset-counters]
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime


def find_test_artifacts(project_root: Path, kind: str) -> list[dict]:
    """Find all test artifacts (label starts with 'test-') for a given kind."""
    artifacts = []
    planning_dir = project_root / ".audiagentic" / "planning"
    kind_dir = planning_dir / kind

    if not kind_dir.exists():
        return artifacts

    for file in kind_dir.glob("*.md"):
        if file.name.startswith("test-"):
            # Read frontmatter to get metadata
            content = file.read_text()
            lines = content.split("\n")

            # Extract label from frontmatter
            label = None
            state = None
            in_frontmatter = False
            for line in lines:
                if line.startswith("---"):
                    if not in_frontmatter:
                        in_frontmatter = True
                    else:
                        break
                    continue

                if in_frontmatter:
                    if line.startswith("label:"):
                        label = line.split(":", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("state:"):
                        state = line.split(":", 1)[1].strip().strip('"').strip("'")

            artifacts.append(
                {
                    "path": file,
                    "id": file.stem,
                    "label": label or file.stem,
                    "state": state,
                }
            )

    return artifacts


def cleanup_test_artifacts(project_root: Path, dry_run: bool = False, reset_counters: bool = False):
    """Remove test artifacts and optionally reset counters."""
    kinds = ["request", "spec", "plan", "task", "wp"]
    counters_file = project_root / ".audiagentic" / "planning" / "ids" / "counters.json"

    total_removed = 0
    counter_adjustments = {}

    for kind in kinds:
        artifacts = find_test_artifacts(project_root, kind)

        if not artifacts:
            print(f"  {kind}: No test artifacts found")
            continue

        print(f"  {kind}: Found {len(artifacts)} test artifact(s)")

        for artifact in artifacts:
            if dry_run:
                print(f"    Would remove: {artifact['id']} ({artifact['label']})")
            else:
                artifact["path"].unlink()
                print(f"    Removed: {artifact['id']}")

            total_removed += 1

            # Track counter adjustments if requested
            if reset_counters:
                kind_counter_key = f"{kind}s" if kind != "wp" else "work-packages"
                if kind_counter_key not in counter_adjustments:
                    counter_adjustments[kind_counter_key] = 0
                counter_adjustments[kind_counter_key] += 1

    # Reset counters if requested
    if reset_counters and counter_adjustments and not dry_run:
        if counters_file.exists():
            counters = json.loads(counters_file.read_text())

            print("\n  Adjusting counters:")
            for kind_key, count in counter_adjustments.items():
                if kind_key in counters:
                    old_value = counters[kind_key]
                    # Find the highest remaining ID for this kind
                    kind = kind_key.rstrip("s") if kind_key != "work-packages" else "wp"
                    kind_dir = project_root / ".audiagentic" / "planning" / kind

                    if kind_dir.exists():
                        remaining_ids = [
                            int(f.stem.split("-")[-1])
                            for f in kind_dir.glob("*.md")
                            if f.stem.split("-")[-1].isdigit()
                        ]
                        new_value = max(remaining_ids) if remaining_ids else 0

                        if new_value < old_value:
                            counters[kind_key] = new_value
                            print(f"    {kind_key}: {old_value} -> {new_value}")

            counters_file.write_text(json.dumps(counters, indent=2) + "\n")
            print("  Counters updated")
        else:
            print("  Warning: counters.json not found, skipping counter reset")

    print(f"\n  Total artifacts removed: {total_removed}")
    return total_removed


def main():
    parser = argparse.ArgumentParser(description="Cleanup test artifacts from planning system")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Root directory of the project (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without actually removing",
    )
    parser.add_argument(
        "--reset-counters", action="store_true", help="Reset ID counters after cleanup"
    )

    args = parser.parse_args()
    project_root = args.project_root.resolve()

    if not (project_root / ".audiagentic").exists():
        print(f"Error: .audiagentic directory not found in {project_root}")
        sys.exit(1)

    print(f"Cleaning up test artifacts in {project_root}")
    print(f"  Dry run: {args.dry_run}")
    print(f"  Reset counters: {args.reset_counters}")
    print()

    removed = cleanup_test_artifacts(
        project_root, dry_run=args.dry_run, reset_counters=args.reset_counters
    )

    if args.dry_run:
        print("\n  Dry run complete. Run without --dry-run to actually remove artifacts.")
    else:
        print(f"\n  Cleanup complete. {removed} artifact(s) removed.")


if __name__ == "__main__":
    main()
