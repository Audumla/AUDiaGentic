#!/usr/bin/env python3
"""
Migrate request IDs from mixed 3-digit/4-digit format to raw integer format.
Renames files, updates frontmatter, replaces all references.

Usage:
    python migrate_request_ids.py --project-root /path/to/repo
"""

import json
import re
import shutil
from pathlib import Path
from typing import Dict


# Mapping: old_id -> new_id
ID_MAPPING = {
    "request-001": "request-1",
    "request-002": "request-2",
    "request-003": "request-3",
    "request-004": "request-4",
    "request-005": "request-5",
    "request-006": "request-6",
    "request-007": "request-7",
    "request-008": "request-8",
    "request-009": "request-9",
    "request-010": "request-10",
    "request-011": "request-11",
    "request-012": "request-12",
    "request-013": "request-13",
    "request-014": "request-14",
    "request-015": "request-15",
    "request-016": "request-16",
    "request-017": "request-17",
    "request-018": "request-18",
    "request-019": "request-19",
    "request-020": "request-20",
    "request-0001": "request-21",
    "request-0002": "request-22",
    "request-0003": "request-23",
    "request-0004": "request-24",
    "request-0021": "request-25",
    "request-0023": "request-26",
    "request-0024": "request-27",
    "request-0027": "request-28",
}


def replace_ids_in_file(file_path: Path) -> int:
    """Replace all old request IDs with new IDs in a file. Return count of replacements."""
    content = file_path.read_text(encoding='utf-8')
    original = content

    # Sort by length descending to replace longest IDs first (avoid partial matches)
    for old_id in sorted(ID_MAPPING.keys(), key=len, reverse=True):
        new_id = ID_MAPPING[old_id]
        content = content.replace(old_id, new_id)

    if content != original:
        file_path.write_text(content, encoding='utf-8')
        return 1
    return 0


def rename_request_files(root: Path) -> int:
    """Rename request files from old to new IDs. Return count of renames."""
    requests_dir = root / "docs" / "planning" / "requests"
    count = 0

    for old_id, new_id in ID_MAPPING.items():
        old_file = requests_dir / f"{old_id}.md"
        new_file = requests_dir / f"{new_id}.md"

        if old_file.exists():
            if new_file.exists():
                print(f"  WARNING: {new_file.name} already exists, skipping rename from {old_file.name}")
            else:
                old_file.rename(new_file)
                # Also rename the extract file if it exists
                old_extract = root / ".audiagentic" / "planning" / "extracts" / f"{old_id}.json"
                new_extract = root / ".audiagentic" / "planning" / "extracts" / f"{new_id}.json"
                if old_extract.exists():
                    old_extract.rename(new_extract)
                print(f"  Renamed {len(old_file.name)}: old: {old_id}, new: {new_id}")
                count += 1
        else:
            print(f"  File not found: {old_file.name}")

    return count


def update_request_frontmatter(root: Path) -> int:
    """Update id field in request file frontmatter. Return count of updates."""
    requests_dir = root / "docs" / "planning" / "requests"
    count = 0

    for md_file in requests_dir.glob("request-*.md"):
        content = md_file.read_text(encoding='utf-8')

        # Extract the filename base (without .md) to infer the new ID
        file_id = md_file.stem

        # Update frontmatter id field to match filename
        pattern = r'^(id:\s+)request-\d+'
        new_content = re.sub(pattern, f'\\1{file_id}', content, flags=re.MULTILINE)

        if new_content != content:
            md_file.write_text(new_content, encoding='utf-8')
            count += 1

    return count


def update_counter_files(root: Path) -> int:
    """Update counter files to reflect new max ID (28). Return count of updates."""
    count = 0

    # Update .audiagentic/planning/ids/counters.json
    counters_file = root / ".audiagentic" / "planning" / "ids" / "counters.json"
    if counters_file.exists():
        try:
            data = json.loads(counters_file.read_text())
            data["request"] = 28
            counters_file.write_text(json.dumps(data, indent=2) + "\n")
            print(f"  Updated: {counters_file.relative_to(root)}")
            count += 1
        except Exception as e:
            print(f"  ERROR updating {counters_file}: {e}")
    else:
        print(f"  File not found: {counters_file}")

    # Update .audiagentic/planning/ids/request.counter
    counter_file = root / ".audiagentic" / "planning" / "ids" / "request.counter"
    if counter_file.exists():
        counter_file.write_text("28")
        print(f"  Updated: {counter_file.relative_to(root)}")
        count += 1
    else:
        print(f"  File not found: {counter_file}")

    # Fix meta directory bug: remove directory, create counter file
    meta_path = root / ".audiagentic" / "planning" / "meta" / "requests.json"
    if meta_path.is_dir():
        shutil.rmtree(meta_path)
        print(f"  Removed directory: {meta_path.relative_to(root)}")
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps({"n": 28}) + "\n")
        print(f"  Created counter file: {meta_path.relative_to(root)}")
        count += 1
    elif meta_path.exists():
        # It's already a file, just update it
        try:
            meta_path.write_text(json.dumps({"n": 28}) + "\n")
            print(f"  Updated: {meta_path.relative_to(root)}")
            count += 1
        except Exception as e:
            print(f"  ERROR updating {meta_path}: {e}")
    else:
        # Create it fresh
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps({"n": 28}) + "\n")
        print(f"  Created: {meta_path.relative_to(root)}")
        count += 1

    return count


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Migrate request IDs to raw integer format")
    parser.add_argument("--project-root", required=True, help="Root of AUDiaGentic repository")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()

    print(f"Starting request ID migration in {root}\n")

    # Step 1: Rename request files and extract files
    print("Step 1: Renaming request files...")
    rename_count = rename_request_files(root)
    print(f"  Renamed: {rename_count} files\n")

    # Step 2: Update request file frontmatter
    print("Step 2: Updating request frontmatter id fields...")
    frontmatter_count = update_request_frontmatter(root)
    print(f"  Updated: {frontmatter_count} files\n")

    # Step 3: Replace IDs in all planning docs
    print("Step 3: Replacing request IDs in planning documents...")
    docs_dir = root / "docs" / "planning"
    replaced = 0
    for md_file in docs_dir.rglob("*.md"):
        if replace_ids_in_file(md_file):
            replaced += 1
    print(f"  Replaced IDs in: {replaced} files\n")

    # Step 4: Replace IDs in index files
    print("Step 4: Replacing request IDs in index files...")
    indexes_dir = root / ".audiagentic" / "planning" / "indexes"
    if indexes_dir.exists():
        replaced = 0
        for json_file in indexes_dir.glob("*.json"):
            if replace_ids_in_file(json_file):
                replaced += 1
        print(f"  Replaced IDs in: {replaced} files\n")
    else:
        print(f"  Indexes directory not found: {indexes_dir}\n")

    # Step 5: Replace IDs in extract files
    print("Step 5: Replacing request IDs in extract files...")
    extracts_dir = root / ".audiagentic" / "planning" / "extracts"
    if extracts_dir.exists():
        replaced = 0
        for json_file in extracts_dir.glob("*.json"):
            if replace_ids_in_file(json_file):
                replaced += 1
        print(f"  Replaced IDs in: {replaced} files\n")
    else:
        print(f"  Extracts directory not found: {extracts_dir}\n")

    # Step 6: Update counter files
    print("Step 6: Updating counter files...")
    counter_count = update_counter_files(root)
    print(f"  Updated: {counter_count} items\n")

    print("Migration complete!")
    print(f"\nNext steps:")
    print(f"  1. Review changes with: git diff")
    print(f"  2. Verify with: python -m audiagentic.planning validate")
    print(f"  3. Regenerate indexes: python tools/reindex.py --project-root {root}")
    print(f"  4. Run tests: pytest tests/")


if __name__ == "__main__":
    main()
