"""
Pass 2: handle remaining 3000-series task IDs missed in pass 1.

- task-3245: has .md, no extract → renumber to task-345
- task-3263: has .md (cancelled), no extract → renumber to task-346
- task-3238: orphaned ref only (no files) → purge from indexes/docs
- task-3246..3250: orphaned in events.jsonl only → purge
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANNING = ROOT / ".audiagentic" / "planning"
DOCS_PLANNING = ROOT / "docs" / "planning"

REMAP = {
    "task-3245": "task-345",
    "task-3263": "task-346",
}

ORPHANED = {"task-3238", "task-3246", "task-3247", "task-3248", "task-3249", "task-3250"}

NEW_COUNTER = 346


def replace_ids_in_text(text: str) -> str:
    for old, new in sorted(REMAP.items(), key=lambda x: -len(x[0])):
        text = text.replace(old, new)
    return text


def purge_orphan_from_json_index(path: Path, orphan_ids: set[str]) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    original = text
    for oid in orphan_ids:
        text = text.replace(oid, f"__REMOVED_{oid}__")
    if text != original:
        # Parse and clean
        # Simpler: just do string replacement then write back
        path.write_text(text, encoding="utf-8")
        return True
    return False


def rename_md_and_update(old_id: str, new_id: str) -> None:
    tasks_dir = DOCS_PLANNING / "tasks" / "core"
    matches = list(tasks_dir.glob(f"{old_id}-*.md"))
    if not matches:
        print(f"  MISSING .md: {old_id}-*.md")
        return
    for old_path in matches:
        slug = old_path.name[len(old_id):]
        new_name = f"{new_id}{slug}"
        new_path = tasks_dir / new_name
        text = replace_ids_in_text(old_path.read_text(encoding="utf-8"))
        new_path.write_text(text, encoding="utf-8")
        old_path.unlink()
        print(f"  .md: {old_path.name} -> {new_name}")


def fix_cross_refs_remap() -> None:
    targets = [
        PLANNING / "indexes" / "lookup.json",
        PLANNING / "indexes" / "readiness.json",
        PLANNING / "indexes" / "tasks.json",
        PLANNING / "indexes" / "trace.json",
        PLANNING / "events" / "events.jsonl",
        ROOT / "docs" / "knowledge" / "data" / "state" / "event-journal.ndjson",
        ROOT / "docs" / "knowledge" / "data" / "state" / "event-state.yml",
        DOCS_PLANNING / "work-packages" / "core" / "wp-0027-standard-0007-implementation-tasks.md",
    ]
    for path in targets:
        if not path.exists():
            print(f"  SKIP: {path.name}")
            continue
        original = path.read_text(encoding="utf-8")
        updated = replace_ids_in_text(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            print(f"  remapped: {path.name}")


def purge_orphaned_from_events() -> None:
    """Remove event lines referencing orphaned IDs from events.jsonl."""
    path = PLANNING / "events" / "events.jsonl"
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = []
    removed = 0
    for line in lines:
        if any(oid in line for oid in ORPHANED):
            removed += 1
        else:
            kept.append(line)
    path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    print(f"  events.jsonl: removed {removed} orphaned-ref lines")


def purge_orphaned_from_indexes() -> None:
    """Remove orphaned task entries from JSON indexes."""
    index_files = [
        PLANNING / "indexes" / "lookup.json",
        PLANNING / "indexes" / "readiness.json",
        PLANNING / "indexes" / "tasks.json",
        PLANNING / "indexes" / "trace.json",
    ]
    for path in index_files:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # JSONL or non-parseable — do string-based removal
            text = path.read_text(encoding="utf-8")
            original = text
            for oid in ORPHANED:
                # Remove lines containing orphaned IDs
                lines = text.splitlines()
                text = "\n".join(l for l in lines if oid not in l)
            if text != original:
                path.write_text(text + "\n", encoding="utf-8")
                print(f"  purged orphans from: {path.name}")
            continue

        changed = False
        # Try top-level dict removal
        for oid in ORPHANED:
            if isinstance(data, dict) and oid in data:
                del data[oid]
                changed = True
            elif isinstance(data, dict):
                # Search nested
                for key in list(data.keys()):
                    if isinstance(data[key], dict) and oid in data[key]:
                        del data[key][oid]
                        changed = True
        if changed:
            path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            print(f"  purged orphans from: {path.name}")


def purge_orphaned_from_wp_md() -> None:
    path = DOCS_PLANNING / "work-packages" / "core" / "wp-0027-standard-0007-implementation-tasks.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    original = text
    for oid in ORPHANED:
        text = re.sub(rf'\b{re.escape(oid)}\b[^\n]*\n?', '', text)
    if text != original:
        path.write_text(text, encoding="utf-8")
        print(f"  purged orphaned refs from: {path.name}")


def update_counter() -> None:
    counters_path = PLANNING / "ids" / "counters.json"
    data = json.loads(counters_path.read_text(encoding="utf-8"))
    old = data["counters"]["task"]
    data["counters"]["task"] = NEW_COUNTER
    counters_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"  counter: task {old} -> {NEW_COUNTER}")


def verify() -> list[str]:
    pattern = re.compile(r"task-3\d{3,}")
    issues = []
    for base in [PLANNING, DOCS_PLANNING]:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".json", ".md", ".yaml", ".yml", ".jsonl", ".ndjson"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            matches = set(pattern.findall(text))
            if matches:
                issues.append(f"  REMAINING: {path.relative_to(ROOT)} -> {matches}")
    return issues


def main() -> None:
    print("=== Step 1: Rename .md files for task-3245 and task-3263 ===")
    for old_id, new_id in REMAP.items():
        rename_md_and_update(old_id, new_id)

    print("\n=== Step 2: Remap references to task-3245 and task-3263 ===")
    fix_cross_refs_remap()

    print("\n=== Step 3: Purge orphaned refs (task-3238, task-3246..3250) from events ===")
    purge_orphaned_from_events()

    print("\n=== Step 4: Purge orphaned refs from indexes ===")
    purge_orphaned_from_indexes()

    print("\n=== Step 5: Purge orphaned refs from wp .md ===")
    purge_orphaned_from_wp_md()

    print("\n=== Step 6: Update counter to 346 ===")
    update_counter()

    print("\n=== Step 7: Verify ===")
    issues = verify()
    if issues:
        print("FAIL — remaining 3000-series references found:")
        for issue in issues:
            print(issue)
    else:
        print("PASS — no 3000-series task IDs remain in planning or docs/planning")


if __name__ == "__main__":
    main()
