"""Guardrail: no raw component ID string literals outside the ids module.

Scans all Python source files and fails if any known component ID appears as a
bare string literal in a file that is not explicitly allowed to contain them.

Allowed files:
  - foundation/components/ids.py          (the source of truth)
  - YAML/config files                     (not scanned here — separate concern)
  - this test file itself

If a new raw component ID string must appear in a test fixture, add it to the
FIXTURE_ALLOW_LIST below with a comment explaining why.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from audiagentic.foundation.components.ids import ALL_COMPONENT_IDS

# Files that are explicitly allowed to contain raw component ID literals.
_SRC = Path(__file__).resolve().parents[4] / "src" / "audiagentic"
_ALLOWED = {
    _SRC / "foundation" / "components" / "ids.py",
}

# Regex: matches a bare string literal containing a component ID.
# Matches both single and double quoted forms, e.g. "project" or 'agent-ledger'.
_LITERAL_RE = re.compile(r"""(?<![#\w])["']({ids})["']""".format(
    ids="|".join(re.escape(cid) for cid in sorted(ALL_COMPONENT_IDS, key=len, reverse=True))
))


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return (line_number, matched_string) for every raw component ID literal."""
    hits: list[tuple[int, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        for m in _LITERAL_RE.finditer(line):
            hits.append((lineno, m.group(0)))
    return hits


def _python_sources() -> list[Path]:
    return [
        p for p in _SRC.rglob("*.py")
        if ".claude" not in p.parts
        and "__pycache__" not in p.parts
        and p not in _ALLOWED
    ]


def test_no_raw_component_ids_in_source() -> None:
    violations: list[str] = []
    for path in sorted(_python_sources()):
        hits = _scan_file(path)
        for lineno, literal in hits:
            rel = path.relative_to(_SRC.parent.parent)
            violations.append(f"{rel}:{lineno}  {literal}")

    if violations:
        report = "\n  ".join(violations)
        pytest.fail(
            f"Raw component ID string literals found in source code.\n"
            f"Import from foundation.components.ids instead:\n\n  {report}"
        )
