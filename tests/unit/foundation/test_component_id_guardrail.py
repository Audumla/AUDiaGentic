"""Guardrail: component ID string literals live only where the doctrine allows.

Post-AR16 doctrine: YAML descriptors are the canonical source for component
IDs. In Python, a component ID literal may appear only in:
  - foundation/components/ids.py            (core semantic branches)
  - the owning component's own package      (self-ID ``_COMPONENT_ID`` pattern)
  - explicitly allowlisted cross-component references (each with a comment)

If a new cross-component reference must appear, add it to _CROSS_REF_ALLOW
with a justification.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Files that are explicitly allowed to contain raw component ID literals.
_SRC = Path(__file__).resolve().parents[4] / "src" / "audiagentic"
_ALLOWED = {
    _SRC / "foundation" / "components" / "ids.py",
}

# Component ID -> owning package directory (self-ID literals allowed there).
_OWNING_DIR = {
    "project": _SRC / "components" / "project",
    "session": _SRC / "components" / "session",
    "agent-jobs": _SRC / "components" / "agent_jobs",
    "agent-ledger": _SRC / "components" / "ledger",
    "providers": _SRC / "components" / "providers",
    "release": _SRC / "components" / "release",
    "source-control": _SRC / "components" / "source_control",
    "coding-lsp": _SRC / "components" / "coding_lsp",
}

# (file, component_id) cross-component references allowed with justification.
_CROSS_REF_ALLOW = {
    # providers renders agent-jobs' prompt-tags contributions on its behalf
    (_SRC / "components" / "providers" / "surfaces" / "contributions.py", "agent-jobs"),
    # source-control probes whether the optional ledger integration is installed
    (_SRC / "components" / "source_control" / "source_control_bootstrap.py", "agent-ledger"),
    # project's dry-run payload uses providers as the example component
    (_SRC / "components" / "project" / "project_api.py", "providers"),
}

_LITERAL_RE = re.compile(r"""(?<![#\w])["']({ids})["']""".format(
    ids="|".join(re.escape(cid) for cid in sorted(_OWNING_DIR, key=len, reverse=True))
))


def _allowed(path: Path, cid: str) -> bool:
    if path in _ALLOWED:
        return True
    owner = _OWNING_DIR.get(cid)
    if owner is not None and owner in path.parents:
        return True
    return (path, cid) in _CROSS_REF_ALLOW


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return (line_number, component_id) for every disallowed literal."""
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
            cid = m.group(1)
            if not _allowed(path, cid):
                hits.append((lineno, cid))
    return hits


def _python_sources() -> list[Path]:
    return [
        p for p in _SRC.rglob("*.py")
        if ".claude" not in p.parts
        and "__pycache__" not in p.parts
    ]


def test_no_raw_component_ids_outside_allowed_locations() -> None:
    violations: list[str] = []
    for path in sorted(_python_sources()):
        for lineno, cid in _scan_file(path):
            rel = path.relative_to(_SRC.parent.parent)
            violations.append(f"{rel}:{lineno}  {cid!r}")

    if violations:
        report = "\n  ".join(violations)
        pytest.fail(
            f"Component ID literals found outside allowed locations.\n"
            f"Use the descriptor registry, the owning component's _COMPONENT_ID, "
            f"or add a justified _CROSS_REF_ALLOW entry:\n\n  {report}"
        )


def test_core_semantic_ids_match_core_descriptors() -> None:
    from audiagentic.foundation.components.ids import CORE_COMPONENT_IDS
    from audiagentic.foundation.components.registry import all_descriptors

    descriptor_ids = frozenset(
        component_id
        for component_id, descriptor in all_descriptors().items()
        if descriptor.core
    )
    assert CORE_COMPONENT_IDS == descriptor_ids
