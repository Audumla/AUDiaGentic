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

# Existing section debt outside the agent-sessions plan, captured when AS70
# introduced the invariant. Exact entries make the baseline shrink-only: new
# omissions fail, and fixed omissions require removal from this list.
_LEGACY_SECTION_DEBT = {
    "AG15": frozenset(["acceptance_criteria"]),
    "AG16": frozenset(["acceptance_criteria", "standards"]),
    "AG18": frozenset(["acceptance_criteria", "standards"]),
    "BR01": frozenset(["validation", "acceptance_criteria", "standards"]),
    "CC27": frozenset(["acceptance_criteria"]),
    "CC29": frozenset(["acceptance_criteria", "standards"]),
    "CC31": frozenset(["acceptance_criteria", "standards"]),
    "CC32": frozenset(["acceptance_criteria", "standards"]),
    "CC37": frozenset(["acceptance_criteria", "standards"]),
    "CC39": frozenset(["validation", "acceptance_criteria", "standards"]),
    "CC41": frozenset(["acceptance_criteria", "standards"]),
    "CC43": frozenset(["acceptance_criteria", "standards"]),
    "CC45": frozenset(["acceptance_criteria"]),
    "CC46": frozenset(["acceptance_criteria"]),
    "CC47": frozenset(["acceptance_criteria"]),
    "CC50": frozenset(["acceptance_criteria"]),
    "LE02": frozenset(["acceptance_criteria", "standards"]),
    "MC03": frozenset(["acceptance_criteria", "standards"]),
    "MI08": frozenset(["acceptance_criteria"]),
    "OB01": frozenset(["acceptance_criteria", "standards"]),
    "PI05": frozenset(["acceptance_criteria", "standards"]),
    "PR03": frozenset(["acceptance_criteria", "standards"]),
    "PT01": frozenset(["acceptance_criteria", "standards"]),
    "PT02": frozenset(["validation", "acceptance_criteria"]),
    "RE01": frozenset(["acceptance_criteria"]),
    # RO01-RO04 removed 2026-08-03: the role-capabilities plan was consumed into
    # agent-sessions (RV886) and all four are superseded. Their successors
    # AS77-AS79 carry acceptance criteria, so the debt is paid rather than moved.
    "SA01": frozenset(["acceptance_criteria"]),
    "SA03": frozenset(["acceptance_criteria"]),
    "SA04": frozenset(["acceptance_criteria"]),
    "SA05": frozenset(["acceptance_criteria"]),
    "SA06": frozenset(["acceptance_criteria"]),
    "SA07": frozenset(["acceptance_criteria"]),
    "SA08": frozenset(["acceptance_criteria"]),
    "SA09": frozenset(["acceptance_criteria"]),
    "SA10": frozenset(["acceptance_criteria"]),
    "SA11": frozenset(["acceptance_criteria"]),
    "SA12": frozenset(["acceptance_criteria"]),
    "SA19": frozenset(["acceptance_criteria"]),
    # TE02 removed 2026-08-03: both sections were filled in, and the baseline
    # is exact shrink-only, so a stale entry fails the guard.
}


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


def _sections(body: str) -> dict[str, str]:
    matches = list(_SECTION_RE.finditer(body))
    result: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        key = re.sub(r"[^a-z0-9]+", " ", match.group(1).lower()).strip()
        result[key] = body[match.end() : end].strip()
    return result


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
    *,
    legacy_section_debt: dict[str, frozenset[str]] | None = None,
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
    observed_legacy_debt: set[tuple[str, str]] = set()
    for path in item_paths:
        frontmatter, body = parsed[path]
        item_id = ids_by_path[path]
        if active_root not in path.parents:
            continue

        sections = _sections(body)
        for required in ("validation", "acceptance criteria"):
            if not sections.get(required):
                debt_key = required.replace(" ", "_")
                if legacy_section_debt and debt_key in legacy_section_debt.get(item_id, frozenset()):
                    observed_legacy_debt.add((item_id, debt_key))
                else:
                    errors.append(f"active item has empty or missing {required.title()} section: {path}")
        if ("src/" in body or ".py" in body) and not sections.get("standards"):
            if legacy_section_debt and "standards" in legacy_section_debt.get(item_id, frozenset()):
                observed_legacy_debt.add((item_id, "standards"))
            else:
                errors.append(f"active code item has empty or missing Standards section: {path}")

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

    for path in review_paths:
        frontmatter, _body = parsed[path]
        state = str(frontmatter.get("state", "created"))
        in_active = active_root in path.parents
        if (state == "closed") == in_active:
            expected = "completed" if state == "closed" else "active"
            errors.append(f"review state/path mismatch; expected {expected}: {path}")

    if legacy_section_debt:
        declared = {
            (item_id, section)
            for item_id, sections in legacy_section_debt.items()
            for section in sections
        }
        for item_id, section in sorted(declared - observed_legacy_debt):
            errors.append(f"stale legacy section-debt baseline: {item_id} now has {section}")

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
    path.write_text(f"---\nid: {item_id}\nplan: sample\nstate: pending\n{dependency}---\n\n{content}", encoding="utf-8")
    return path


def test_repository_plan_set_is_consistent():
    assert validate_plan_set(
        REPO_ROOT / "docs" / "planning",
        legacy_section_debt=_LEGACY_SECTION_DEBT,
    ) == []


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


def test_required_sections_must_be_non_empty(tmp_path):
    _write_item(tmp_path, "TS01", body="# Item\n\nTouches `src/example.py`.\n\n## Validation\n\n## Acceptance criteria\n\nDone.\n\n## Standards\n")
    errors = validate_plan_set(tmp_path)
    assert any("Validation" in error for error in errors)
    assert any("Standards" in error for error in errors)
