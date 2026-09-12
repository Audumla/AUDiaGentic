"""Repository-level integrity checks for the planning document set."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from audiagentic.foundation.paths.package import REPO_ROOT
from audiagentic.foundation.workflow.frontmatter import parse_frontmatter

_STATE_DIRS = ("active", "completed")
_FENCED_BLOCK_RE = re.compile(r"^\s*```.*?^\s*```\s*$", re.MULTILINE | re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_ITEM_FILENAME_RE = re.compile(r"^[A-Z]+\d+$")

def _item_paths(planning_root: Path) -> list[Path]:
    """Return canonical item files, excluding reviews and auxiliary trees."""
    return sorted(
        path
        for state in _STATE_DIRS
        for path in (planning_root / state).glob("*/*.md")
        if _ITEM_FILENAME_RE.fullmatch(path.stem)
    )


def _review_paths(planning_root: Path) -> list[Path]:
    return sorted(
        path
        for state in _STATE_DIRS
        for path in (planning_root / state).glob("*/reviews/*/*.md")
    )


def _read(path: Path) -> tuple[dict[str, Any], str]:
    return parse_frontmatter(path.read_text(encoding="utf-8"))


def _string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _string_values(nested)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _string_values(nested)


def validate_plan_set(
    planning_root: Path,
) -> list[str]:
    """Return actionable violations of repository planning invariants."""
    item_paths = _item_paths(planning_root)
    review_paths = _review_paths(planning_root)
    documents = item_paths + review_paths
    parsed = {path: _read(path) for path in documents}
    errors: list[str] = []

    ids_by_path = {
        path: str(frontmatter.get("id", ""))
        for path, (frontmatter, _body) in parsed.items()
    }
    counts = Counter(ids_by_path.values())
    for item_id, count in sorted(counts.items()):
        if not item_id:
            continue
        if count > 1:
            locations = ", ".join(str(path) for path, value in ids_by_path.items() if value == item_id)
            errors.append(f"duplicate planning ID {item_id}: {locations}")

    for path, item_id in ids_by_path.items():
        if not item_id:
            errors.append(f"missing frontmatter id: {path}")
        elif path.stem != item_id:
            errors.append(f"filename/id mismatch: {path} declares {item_id}")

    item_ids = {ids_by_path[path] for path in item_paths if ids_by_path[path]}
    prefixes = sorted(
        {match.group(1) for item_id in item_ids if (match := re.fullmatch(r"([A-Z]+)\d+", item_id))},
        key=len,
        reverse=True,
    )
    reference_re = (
        re.compile(rf"(?<![A-Za-z0-9])(?:{'|'.join(map(re.escape, prefixes))})\d+(?![A-Za-z0-9])")
        if prefixes
        else None
    )

    active_root = planning_root / "active"
    for path in item_paths:
        _frontmatter, body = parsed[path]
        if active_root not in path.parents:
            continue

        if reference_re:
            prose = _FENCED_BLOCK_RE.sub("", body)
            missing = sorted(set(reference_re.findall(prose)) - item_ids)
            if missing:
                errors.append(f"active item has unresolved references {missing}: {path}")

    graph: dict[str, set[str]] = {item_id: set() for item_id in item_ids}
    if reference_re:
        for path in item_paths:
            frontmatter, _body = parsed[path]
            item_id = ids_by_path[path]
            blocked_by = frontmatter.get("blocked-by", frontmatter.get("blocked_by"))
            targets = {
                match
                for value in _string_values(blocked_by)
                for match in reference_re.findall(value)
            }
            missing = sorted(targets - item_ids)
            if missing:
                errors.append(f"blocked-by has unresolved targets {missing}: {path}")
            if item_id:
                graph[item_id].update(targets & item_ids)

    visiting: list[str] = []
    visited: set[str] = set()

    def visit(item_id: str) -> None:
        if item_id in visiting:
            cycle = visiting[visiting.index(item_id) :] + [item_id]
            errors.append(f"blocked-by cycle: {' -> '.join(cycle)}")
            return
        if item_id in visited:
            return
        visiting.append(item_id)
        for target in sorted(graph[item_id]):
            visit(target)
        visiting.pop()
        visited.add(item_id)

    for item_id in sorted(graph):
        visit(item_id)

    active_root = planning_root / "active"
    for path in review_paths:
        frontmatter, _body = parsed[path]
        state = str(frontmatter.get("state", "created"))
        in_active = active_root in path.parents
        if (state == "closed") == in_active:
            expected = "completed" if state == "closed" else "active"
            errors.append(f"review state/path mismatch; expected {expected}: {path}")

    return errors


def _write_item(
    root: Path,
    item_id: str,
    *,
    state_dir: str = "active",
    filename: str | None = None,
    blocked_by: str | None = None,
    body: str | None = None,
) -> Path:
    path = root / state_dir / "sample" / f"{filename or item_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    dependency = f"blocked-by: {blocked_by}\n" if blocked_by else ""
    content = body or "# Item\n\n## Validation\n\nRun tests.\n\n## Acceptance criteria\n\nTests pass.\n"
    state = "completed" if state_dir == "completed" else "pending"
    path.write_text(f"---\nid: {item_id}\nplan: sample\nstate: {state}\n{dependency}---\n\n{content}", encoding="utf-8")
    return path


def test_repository_plan_set_is_consistent():
    assert validate_plan_set(REPO_ROOT / "docs" / "planning") == []


def test_duplicate_id_and_cross_state_copy_fail(tmp_path):
    _write_item(tmp_path, "TS01")
    _write_item(tmp_path, "TS01", state_dir="completed")
    assert any("duplicate planning ID TS01" in error for error in validate_plan_set(tmp_path))


def test_filename_must_match_frontmatter_id(tmp_path):
    _write_item(tmp_path, "TS01", filename="TS02")
    assert any("filename/id mismatch" in error for error in validate_plan_set(tmp_path))


def test_unresolved_active_reference_fails_but_fenced_example_is_ignored(tmp_path):
    _write_item(tmp_path, "TS01", body="# Item\n\nTS99 is missing.\n\n```text\nTS98\n```\n\n## Validation\n\nRun.\n\n## Acceptance criteria\n\nPass.\n")
    errors = validate_plan_set(tmp_path)
    assert any("TS99" in error for error in errors)
    assert all("TS98" not in error for error in errors)


def test_blocked_by_cycle_fails(tmp_path):
    _write_item(tmp_path, "TS01", blocked_by="TS02")
    _write_item(tmp_path, "TS02", blocked_by="TS01")
    assert any("blocked-by cycle: TS01 -> TS02 -> TS01" in error for error in validate_plan_set(tmp_path))


def test_pending_drafts_may_omit_completion_sections(tmp_path):
    _write_item(
        tmp_path,
        "TS01",
        body="# Item\n\nTouches `src/example.py`.\n\n## Validation\n\n## Acceptance criteria\n\nDone.\n\n## Standards\n",
    )
    assert validate_plan_set(tmp_path) == []
