"""
Reformat all padded IDs in the v14 external pack to raw integer format.

Maps pack padded IDs to live-lane sequential raw IDs based on current counters.
Also renames all .md files to match the new IDs.
Updates the import readiness map with the final remap.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1] / "external_packs" / "audiagentic_stage1_planning_pack_v14_import_ready"
DOCS = PACK / "docs" / "planning"

# Full remap: padded pack ID → raw live-lane ID
# Planning item IDs (based on current live counters: plan=22, request=31, spec=79, task=346, wp=27)
REMAP = {
    # planning items
    "plan-0023": "plan-23",
    "request-021": "request-32",
    "spec-0080": "spec-80",
    "spec-0081": "spec-81",
    "spec-0082": "spec-82",
    "spec-0083": "spec-83",
    "spec-0084": "spec-84",
    "spec-0085": "spec-85",
    "task-0348": "task-347",
    "task-0349": "task-348",
    "task-0350": "task-349",
    "task-0351": "task-350",
    "task-0352": "task-351",
    "task-0353": "task-352",
    "task-0354": "task-353",
    "task-0355": "task-354",
    "task-0356": "task-355",
    "task-0357": "task-356",
    "task-0358": "task-357",
    "task-0359": "task-358",
    "task-0360": "task-359",
    "task-0361": "task-360",
    "wp-0028": "wp-28",
    "wp-0029": "wp-29",
    "wp-0030": "wp-30",
    "wp-0031": "wp-31",
    # standard refs (padded → raw, matching live lane)
    "standard-0004": "standard-4",
    "standard-0005": "standard-5",
    "standard-0006": "standard-6",
    "standard-0007": "standard-7",
    "standard-0008": "standard-8",
    "standard-0011": "standard-11",
}


def replace_all(text: str) -> str:
    # Sort longest first to prevent partial matches (e.g. spec-0080 before spec-008)
    for old, new in sorted(REMAP.items(), key=lambda x: -len(x[0])):
        text = text.replace(old, new)
    return text


def new_filename(path: Path) -> str:
    """Derive new filename by replacing old ID prefix with new ID."""
    name = path.name
    for old, new in sorted(REMAP.items(), key=lambda x: -len(x[0])):
        if name.startswith(old):
            return new + name[len(old):]
    return name


def process_file(path: Path) -> bool:
    original = path.read_text(encoding="utf-8")
    updated = replace_all(original)
    changed = updated != original
    if changed:
        path.write_text(updated, encoding="utf-8")
    return changed


def rename_file(path: Path) -> Path | None:
    new_name = new_filename(path)
    if new_name == path.name:
        return None
    new_path = path.parent / new_name
    path.rename(new_path)
    return new_path


def verify() -> list[str]:
    padded = re.compile(r'\b(plan|request|spec|task|wp|standard)-0\d+\b')
    issues = []
    for path in DOCS.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        matches = set(padded.findall(text))
        if matches:
            issues.append(f"  {path.relative_to(PACK)}: still padded → {matches}")
    return issues


def update_readiness_map() -> None:
    map_path = DOCS / "supporting" / "installer-v14-import-readiness-map.md"
    if not map_path.exists():
        return
    text = map_path.read_text(encoding="utf-8")

    new_section = """## Current live-safe IDs (raw integer format)

All IDs use raw integer format matching the live planning lane (`kind-n`, no padding).

- request: `request-32`
- specs: `spec-80` through `spec-85`
- plan: `plan-23`
- work packages: `wp-28` through `wp-31`
- tasks: `task-347` through `task-360`

## ID remap from padded pack format to live-safe raw format

| Pack (padded) | Live-safe (raw) |
|---|---|
| request-021 | request-32 |
| spec-0080 | spec-80 |
| spec-0081 | spec-81 |
| spec-0082 | spec-82 |
| spec-0083 | spec-83 |
| spec-0084 | spec-84 |
| spec-0085 | spec-85 |
| plan-0023 | plan-23 |
| wp-0028 | wp-28 |
| wp-0029 | wp-29 |
| wp-0030 | wp-30 |
| wp-0031 | wp-31 |
| task-0348 | task-347 |
| task-0349 | task-348 |
| task-0350 | task-349 |
| task-0351 | task-350 |
| task-0352 | task-351 |
| task-0353 | task-352 |
| task-0354 | task-353 |
| task-0355 | task-354 |
| task-0356 | task-355 |
| task-0357 | task-356 |
| task-0358 | task-357 |
| task-0359 | task-358 |
| task-0360 | task-359 |
| task-0361 | task-360 |

## Pre-import rule

Re-run a live collision check immediately before import. If any ID is now occupied,
create a fresh remap — do not import stale IDs.

## v14 additions (component lifecycle)

Added after initial v14 recut. No predecessor IDs — these are new items:

- `spec-85` (new) — component lifecycle manifest schema and semantics
- `task-359` (new) — freeze component lifecycle manifest schema (wp-28, seq 4000)
- `task-360` (new) — freeze disable and uninstall reconcile behavior (wp-29, seq 4000)
"""

    # Replace entire file content (it's a readiness map, full replacement is correct)
    header = "# Installer v14 import-ready status\n\n## Status\n\nThis copy is reformatted to raw integer IDs matching live planning lane format (`kind-n`, no zero-padding).\n\nIt remains external only. Not imported.\n\n"
    map_path.write_text(header + new_section, encoding="utf-8")
    print(f"  updated: {map_path.name}")


def main() -> None:
    print("=== Step 1: Update file contents ===")
    for path in sorted(DOCS.rglob("*.md")):
        changed = process_file(path)
        if changed:
            print(f"  updated: {path.relative_to(DOCS)}")

    print("\n=== Step 2: Rename files ===")
    # Process deepest paths first to avoid renaming parents before children
    for path in sorted(DOCS.rglob("*.md"), key=lambda p: -len(p.parts)):
        new_path = rename_file(path)
        if new_path:
            print(f"  {path.name} -> {new_path.name}")

    print("\n=== Step 3: Update import readiness map ===")
    update_readiness_map()

    print("\n=== Step 4: Verify no padded IDs remain ===")
    issues = verify()
    if issues:
        print("FAIL — padded IDs remain:")
        for i in issues:
            print(i)
        sys.exit(1)
    else:
        print("PASS — all IDs are raw integer format")


if __name__ == "__main__":
    main()
