#!/usr/bin/env python3
"""Migrate padded IDs (spec-001) to raw format (spec-1).

This script:
1. Finds all items with padded IDs (spec-001, task-0012, etc)
2. Renumbers them to raw format (spec-1, task-12)
3. Updates all cross-references in planning items
4. Updates counter files
5. Rebuilds planning state via maintain()

Safe to run multiple times — idempotent by checking if item is already raw.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from audiagentic.planning.fs.scan import scan_items
from audiagentic.planning.app.api import PlanningAPI


def _strip_padding(id_: str) -> str | None:
    """Convert padded ID to raw: spec-001 -> spec-1, task-0012 -> task-12."""
    m = re.match(r"^([a-z]+)-0+(\d+)$", id_)
    if not m:
        return None  # Not padded, or invalid format
    kind, num_str = m.groups()
    num = int(num_str)
    return f"{kind}-{num}"


def migrate_ids():
    """Main migration: rename files, update refs, update counters."""
    api = PlanningAPI(ROOT)
    items = [i for i in scan_items(ROOT) if not i.data.get("deleted")]

    # Find all items needing renumbering
    to_migrate = []
    for item in items:
        raw_id = _strip_padding(item.data["id"])
        if raw_id and raw_id != item.data["id"]:
            to_migrate.append((item.data["id"], raw_id, item.path))

    if not to_migrate:
        print("No padded IDs found — nothing to migrate")
        return

    print(f"Found {len(to_migrate)} items to renumber:")
    for old_id, new_id, path in to_migrate[:10]:
        print(f"  {old_id:20s} -> {new_id}")
    if len(to_migrate) > 10:
        print(f"  ... and {len(to_migrate) - 10} more")

    # Build mapping
    id_map = {old_id: new_id for old_id, new_id, _ in to_migrate}

    # 1. Update each item's frontmatter ID
    print("\nUpdating frontmatter IDs...")
    for old_id, new_id, path in to_migrate:
        content = path.read_text(encoding="utf-8")
        content = content.replace(f"id: {old_id}\n", f"id: {new_id}\n")
        path.write_text(content, encoding="utf-8")
        print(f"  {old_id} -> {new_id}")

    # 2. Scan for cross-references and update them
    print("\nUpdating cross-references in other items...")
    ref_fields = [
        "spec_ref",
        "plan_ref",
        "request_refs",
        "task_refs",
        "parent_task_ref",
        "standard_refs",
    ]
    updated_refs = 0

    for item in scan_items(ROOT):
        if item.data.get("deleted"):
            continue
        content = item.path.read_text(encoding="utf-8")
        original = content
        for old_id, new_id in id_map.items():
            # Replace in YAML frontmatter
            content = re.sub(
                rf"^({old_id})\b",
                new_id,
                content,
                flags=re.MULTILINE,
            )
            # Replace in list contexts (e.g., task_refs: [task-0012, ...])
            content = content.replace(f": {old_id}", f": {new_id}")
            content = content.replace(f"- {old_id}", f"- {new_id}")
            content = content.replace(f"  ref: {old_id}", f"  ref: {new_id}")

        if content != original:
            item.path.write_text(content, encoding="utf-8")
            updated_refs += 1
            print(f"  Updated refs in {item.data['id']}")

    print(f"Updated {updated_refs} items with cross-references")

    # 3. Update counter files
    print("\nUpdating counter files...")
    counters_file = ROOT / ".audiagentic" / "planning" / "ids" / "counters.json"
    if counters_file.exists():
        counters = json.loads(counters_file.read_text(encoding="utf-8"))
        counters_data = counters.get("counters", {})
        for old_id, new_id in id_map.items():
            m = re.match(r"^([a-z]+)-\d+$", new_id)
            if m:
                kind = m.group(1)
                num = int(re.match(r"^[a-z]+-(\d+)$", new_id).group(1))
                if kind in counters_data:
                    counters_data[kind] = max(counters_data[kind], num)
        counters_file.write_text(json.dumps(counters, indent=2), encoding="utf-8")
        print(f"Updated counters: {counters_data}")

    # 4. Run maintain to reconcile filenames and rebuild indexes
    print("\nRunning maintain() to reconcile filenames and rebuild state...")
    result = api.maintain()
    print(f"  Filenames renamed: {len(result['renames'])}")
    print(f"  Indexes rebuilt: {result['indexes_rebuilt']}")
    print(f"  Extracts rebuilt: {result['extracts_rebuilt']}")
    if result["orphans"]:
        print(f"  Orphans: {result['orphans']}")

    print("\nMigration complete!")


if __name__ == "__main__":
    migrate_ids()
