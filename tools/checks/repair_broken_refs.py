#!/usr/bin/env python3
"""Repair broken references in planning documents."""

import os
import re
import yaml
from pathlib import Path
from collections import defaultdict

PLANNING_DIR = Path("docs/planning")


def load_valid_ids():
    """Load valid IDs from planning directories."""
    valid = defaultdict(set)

    for kind in ["task", "plan", "spec", "wp"]:
        dir_map = {
            "task": "tasks",
            "plan": "plans",
            "spec": "specifications",
            "wp": "work-packages",
        }
        dir_path = PLANNING_DIR / dir_map[kind]
        if dir_path.exists():
            for md_file in dir_path.rglob("*.md"):
                # Extract ID from filename like task-0008.md or spec-0023-xxx.md
                stem = md_file.stem  # e.g., task-0008 or spec-0023-archive-...
                parts = stem.split("-")
                # Extract just the ID portion (e.g., spec-0023)
                if len(parts) >= 2:
                    id_portion = parts[0] + "-" + parts[1]  # spec-0023
                    valid[kind].add(id_portion)

    return valid


def extract_refs_from_file(file_path, check_body_text=False):
    """Extract all references from a markdown file.

    By default, only checks YAML frontmatter metadata fields (spec_refs, task_refs, etc.)
    since body text references are often historical/documentation and don't cause issues.

    Args:
        file_path: Path to the markdown file
        check_body_text: If True, also check body text (not just metadata)

    Returns:
        defaultdict with kind -> list of refs
    """
    refs = defaultdict(list)

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        return refs

    # Find YAML frontmatter
    frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n"
    frontmatter_match = re.search(frontmatter_pattern, content, re.DOTALL)

    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)

        # Remove id: line to avoid self-references
        frontmatter = re.sub(r"^id:\s*\S+\s*$", "", frontmatter, flags=re.MULTILINE)

        # Extract refs from frontmatter (metadata fields)
        pattern = r"(task|plan|spec|wp)-\d+"
        for match in re.finditer(pattern, frontmatter):
            ref = match.group(0)
            kind = ref.split("-")[0]
            refs[kind].append(ref)

    # Optionally check body text (for debugging/historical analysis)
    if check_body_text:
        body = content[frontmatter_match.end() :] if frontmatter_match else content

        # Remove code blocks
        body = re.sub(r"```[\s\S]*?```", "", body)
        body = re.sub(r"~~~[\s\S]*?~~~", "", body)

        # Extract refs from body
        pattern = r"(task|plan|spec|wp)-\d+"
        for match in re.finditer(pattern, body):
            ref = match.group(0)
            kind = ref.split("-")[0]
            refs[kind].append(ref)

    return refs

    # Remove YAML frontmatter id field to avoid self-references
    # Find and remove the id: XXXX line from frontmatter
    frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n"
    frontmatter_match = re.search(frontmatter_pattern, content, re.DOTALL)

    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        # Remove id: line from frontmatter
        frontmatter_clean = re.sub(r"^id:\s*\S+\s*$", "", frontmatter, flags=re.MULTILINE)
        # Reconstruct content without id in frontmatter
        content = (
            content[: frontmatter_match.start()]
            + "---\n"
            + frontmatter_clean
            + "\n---"
            + content[frontmatter_match.end() :]
        )

    # Remove code blocks (both fenced and indented)
    # Fenced code blocks with ```
    content = re.sub(r"```[\s\S]*?```", "", content)
    # Fenced code blocks with ~~~
    content = re.sub(r"~~~[\s\S]*?~~~", "", content)

    # Pattern to match task-XXXX, plan-XXXX, spec-XXXX, wp-XXXX
    pattern = r"(task|plan|spec|wp)-\d+"

    for match in re.finditer(pattern, content):
        ref = match.group(0)
        kind = ref.split("-")[0]
        refs[kind].append(ref)

    return refs

    # Remove YAML frontmatter id field to avoid self-references
    # Find and remove the id: XXXX line from frontmatter
    frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n"
    frontmatter_match = re.search(frontmatter_pattern, content, re.DOTALL)

    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        # Remove id: line from frontmatter
        frontmatter_clean = re.sub(r"^id:\s*\S+\s*$", "", frontmatter, flags=re.MULTILINE)
        # Reconstruct content without id in frontmatter
        content = (
            content[: frontmatter_match.start()]
            + "---\n"
            + frontmatter_clean
            + "\n---"
            + content[frontmatter_match.end() :]
        )

    # Pattern to match task-XXXX, plan-XXXX, spec-XXXX, wp-XXXX
    pattern = r"(task|plan|spec|wp)-\d+"

    for match in re.finditer(pattern, content):
        ref = match.group(0)
        kind = ref.split("-")[0]
        refs[kind].append(ref)

    return refs

    # Pattern to match task-XXXX, plan-XXXX, spec-XXXX, wp-XXXX
    pattern = r"(task|plan|spec|wp)-\d+"

    for match in re.finditer(pattern, content):
        ref = match.group(0)
        kind = ref.split("-")[0]
        refs[kind].append(ref)

    return refs


def find_broken_refs(valid_ids, check_body_text=False):
    """Find all broken references across planning documents.

    By default, only checks metadata fields (YAML frontmatter) since body text
    references are often historical/documentation and don't cause actual issues.

    Args:
        valid_ids: Dict of valid IDs by kind
        check_body_text: If True, also check body text references

    Returns:
        defaultdict with file_path -> list of (kind, ref) tuples
    """
    broken = defaultdict(list)  # {file_path: [(kind, ref), ...]}

    # Search in plans, specs, requests, standards, and docs
    search_dirs = [
        PLANNING_DIR / "plans",
        PLANNING_DIR / "specifications",
        PLANNING_DIR / "requests",
        PLANNING_DIR / "standards",
        PLANNING_DIR / "docs",
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue

        for md_file in search_dir.rglob("*.md"):
            refs = extract_refs_from_file(md_file, check_body_text=check_body_text)

            for kind, ref_list in refs.items():
                for ref in ref_list:
                    if ref not in valid_ids[kind]:
                        broken[md_file].append((kind, ref))

    return broken


def report_broken_refs(broken):
    """Report broken references by file."""
    print(f"\n{'=' * 60}")
    print("BROKEN REFERENCES REPORT")
    print(f"{'=' * 60}\n")

    total_broken = 0
    by_kind = defaultdict(int)

    for file_path, refs in sorted(broken.items()):
        # Handle both Path objects and strings
        if isinstance(file_path, Path):
            try:
                rel_path = file_path.relative_to(Path.cwd())
            except ValueError:
                rel_path = file_path
        else:
            rel_path = file_path
        print(f"\n{rel_path}:")

        for kind, ref in sorted(set(refs)):
            print(f"  - {ref}")
            total_broken += 1
            by_kind[kind] += 1

    print(f"\n{'=' * 60}")
    print(f"TOTAL BROKEN REFERENCES: {total_broken}")
    print(f"{'=' * 60}")
    print("\nBy kind:")
    for kind, count in sorted(by_kind.items()):
        print(f"  {kind}: {count}")

    return total_broken


def repair_broken_refs_in_metadata(file_path, broken_refs, valid_ids, dry_run=True):
    """Remove broken references from YAML frontmatter metadata fields."""
    try:
        content = file_path.read_text(encoding="utf-8")
        original_content = content

        # Find YAML frontmatter
        frontmatter_pattern = r"^(---\s*\n(.*?)\n---)"
        frontmatter_match = re.search(frontmatter_pattern, content, re.DOTALL)

        if not frontmatter_match:
            return False

        frontmatter = frontmatter_match.group(0)
        frontmatter_body = frontmatter_match.group(2)

        # Get list of broken refs (just the ref strings, not kinds)
        broken_ref_list = list(set(ref for kind, ref in broken_refs))

        # Remove broken refs from list fields in frontmatter
        # Pattern for list items like "- spec-0003"
        for broken_ref in broken_ref_list:
            # Remove list items
            frontmatter_body = re.sub(
                rf"^\s*-\s*{re.escape(broken_ref)}(?:\s*#.*)?$\n?",
                "",
                frontmatter_body,
                flags=re.MULTILINE,
            )
            # Remove ref: value pairs in work_package_refs
            frontmatter_body = re.sub(
                rf"^\s*-\s*ref:\s*{re.escape(broken_ref)}\n\s*[^:\n]+:[^,\n]+\n?",
                "",
                frontmatter_body,
                flags=re.MULTILINE,
            )

        # Reconstruct frontmatter
        new_frontmatter = "---\n" + frontmatter_body + "---"
        content = (
            content[: frontmatter_match.start()]
            + new_frontmatter
            + content[frontmatter_match.end() :]
        )

        # Clean up any empty lines
        content = re.sub(r"\n{3,}", "\n\n", content)

        if content != original_content and not dry_run:
            file_path.write_text(content, encoding="utf-8")
            return True

        return False
    except Exception as e:
        print(f"  Error repairing {file_path}: {e}")
        return False


def main():
    print("Loading valid IDs...")
    valid_ids = load_valid_ids()

    print(f"  tasks: {len(valid_ids['task'])}")
    print(f"  plans: {len(valid_ids['plan'])}")
    print(f"  specs: {len(valid_ids['spec'])}")
    print(f"  wps: {len(valid_ids['wp'])}")

    print("\nFinding broken references in METADATA FIELDS only...")
    print("(Body text references are excluded as they are often historical/documentation)")
    broken = find_broken_refs(valid_ids, check_body_text=False)

    total = report_broken_refs(broken)

    if total == 0:
        print("\n[OK] No broken references in metadata fields!")
        print("\nNote: Body text may still contain historical references to deleted items.")
        print("Run with --check-body to include body text in the check.")
    else:
        print(f"\n[!] Found {total} broken references in metadata across {len(broken)} files")
        print("\nThese are ACTUAL broken links that should be fixed.")

        # Ask user if they want to repair
        print("\n" + "=" * 60)
        print("REPAIR OPTIONS:")
        print("=" * 60)
        print("1. Remove broken refs from metadata fields (safe)")
        print("2. Check body text too (for historical references)")
        print("3. Exit without changes")

        try:
            choice = input("\nEnter choice [1-3]: ").strip()
        except EOFError:
            choice = "3"

        if choice == "1":
            print("\n" + "=" * 60)
            print("REMOVING BROKEN REFS FROM METADATA FIELDS...")
            print("=" * 60)

            repaired_count = 0
            for file_path, refs in sorted(broken.items()):
                if repair_broken_refs_in_metadata(file_path, refs, valid_ids, dry_run=False):
                    print(f"  Repaired: {file_path}")
                    repaired_count += 1
                else:
                    print(f"  Skipped: {file_path}")

            print(f"\nRepaired {repaired_count} files")

            # Re-run the check
            print("\nRe-checking for broken references...")
            broken_after = find_broken_refs(valid_ids)
            total_after = sum(len(refs) for refs in broken_after.values())
            print(f"Remaining broken references: {total_after}")

        elif choice == "2":
            print("\n" + "=" * 60)
            print("CHECKING BODY TEXT REFERENCES...")
            print("=" * 60)
            broken_full = find_broken_refs(valid_ids, check_body_text=True)
            total_full = sum(len(refs) for refs in broken_full.values())
            print(f"\nTotal broken references (including body text): {total_full}")
            print(f"Body text only: {total_full - total}")
            print("\nBody text references are typically historical/documentation.")
            print("They do not cause actual issues and can be safely ignored.")

        else:
            print("\nNo changes made")


if __name__ == "__main__":
    main()
