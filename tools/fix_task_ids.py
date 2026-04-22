"""
Renumber 3000-series task IDs to sequential IDs starting at 336.
Updates extract JSONs, .md files, cross-references, indexes, events, and counters.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANNING = ROOT / ".audiagentic" / "planning"
DOCS_PLANNING = ROOT / "docs" / "planning"

# Remap: old id -> new id
REMAP = {
    "task-3000": "task-336",
    "task-3251": "task-337",
    "task-3252": "task-338",
    "task-3253": "task-339",
    "task-3258": "task-340",
    "task-3259": "task-341",
    "task-3261": "task-342",
    "task-3262": "task-343",
    "task-3264": "task-344",
}

NEW_COUNTER = 344


def replace_ids_in_text(text: str) -> str:
    """Replace all old IDs with new IDs. Longest IDs first to avoid partial matches."""
    for old, new in sorted(REMAP.items(), key=lambda x: -len(x[0])):
        text = text.replace(old, new)
    return text


def fix_json_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = replace_ids_in_text(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def fix_text_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = replace_ids_in_text(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def rename_extract(old_id: str, new_id: str) -> None:
    old_path = PLANNING / "extracts" / f"{old_id}.json"
    new_path = PLANNING / "extracts" / f"{new_id}.json"
    if not old_path.exists():
        print(f"  MISSING extract: {old_path}")
        return
    # Update internal content first
    data = json.loads(old_path.read_text(encoding="utf-8"))
    text = replace_ids_in_text(old_path.read_text(encoding="utf-8"))
    new_path.write_text(text, encoding="utf-8")
    old_path.unlink()
    print(f"  extract: {old_id}.json -> {new_id}.json")


def rename_md_file(old_id: str, new_id: str) -> None:
    tasks_dir = DOCS_PLANNING / "tasks" / "core"
    # Find by prefix
    matches = list(tasks_dir.glob(f"{old_id}-*.md"))
    if not matches:
        print(f"  MISSING .md: {old_id}-*.md")
        return
    for old_path in matches:
        slug = old_path.name[len(old_id):]  # e.g. "-refactor-section-registry.md"
        new_name = f"{new_id}{slug}"
        new_path = tasks_dir / new_name
        text = replace_ids_in_text(old_path.read_text(encoding="utf-8"))
        new_path.write_text(text, encoding="utf-8")
        old_path.unlink()
        print(f"  .md: {old_path.name} -> {new_name}")


def fix_cross_references() -> None:
    """Fix all non-task files that reference 3000-series IDs."""
    targets = [
        # extracts with cross-refs
        PLANNING / "extracts" / "request-25.json",
        PLANNING / "extracts" / "spec-29.json",
        PLANNING / "extracts" / "task-28.json",
        PLANNING / "extracts" / "task-332.json",
        PLANNING / "extracts" / "wp-18.json",
        # indexes
        PLANNING / "indexes" / "lookup.json",
        PLANNING / "indexes" / "readiness.json",
        PLANNING / "indexes" / "tasks.json",
        PLANNING / "indexes" / "trace.json",
        # events
        PLANNING / "events" / "events.jsonl",
        # knowledge state (functional, not archive)
        ROOT / "docs" / "knowledge" / "data" / "state" / "event-journal.ndjson",
        ROOT / "docs" / "knowledge" / "data" / "state" / "event-state.yml",
        # docs planning cross-refs
        DOCS_PLANNING / "requests" / "request-25-config-driven-planning-document-structure.md",
        DOCS_PLANNING / "specifications" / "spec-29-config-driven-planning-document-structure.md",
        DOCS_PLANNING / "tasks" / "core" / "task-28-verify-test-coverage-for-config-driven-planning-create-paths.md",
        DOCS_PLANNING / "tasks" / "core" / "task-332-refactor-managers-to-use-config.md",
        DOCS_PLANNING / "work-packages" / "core" / "wp-18-phase-3-manager-refactoring.md",
    ]
    for path in targets:
        if not path.exists():
            print(f"  SKIP (not found): {path.name}")
            continue
        changed = fix_text_file(path)
        if changed:
            print(f"  cross-ref updated: {path.name}")


def update_counter() -> None:
    counters_path = PLANNING / "ids" / "counters.json"
    data = json.loads(counters_path.read_text(encoding="utf-8"))
    old = data["counters"]["task"]
    data["counters"]["task"] = NEW_COUNTER
    counters_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"  counter: task {old} -> {NEW_COUNTER}")


def verify() -> list[str]:
    """Check no 3000-series IDs remain in planning or docs/planning."""
    issues = []
    pattern = re.compile(r"task-3\d{3,}")
    search_dirs = [PLANNING, DOCS_PLANNING]
    for base in search_dirs:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".json", ".md", ".yaml", ".yml", ".jsonl", ".ndjson"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            matches = pattern.findall(text)
            if matches:
                issues.append(f"  REMAINING: {path.relative_to(ROOT)} -> {set(matches)}")
    return issues


def main() -> None:
    print("=== Step 1: Rename extract JSON files ===")
    for old_id, new_id in REMAP.items():
        rename_extract(old_id, new_id)

    print("\n=== Step 2: Rename .md task files ===")
    for old_id, new_id in REMAP.items():
        rename_md_file(old_id, new_id)

    print("\n=== Step 3: Fix cross-references ===")
    fix_cross_references()

    print("\n=== Step 4: Update counter ===")
    update_counter()

    print("\n=== Step 5: Verify ===")
    issues = verify()
    if issues:
        print("FAIL — remaining 3000-series references found:")
        for issue in issues:
            print(issue)
    else:
        print("PASS — no 3000-series task IDs remain in planning or docs/planning")


if __name__ == "__main__":
    main()
