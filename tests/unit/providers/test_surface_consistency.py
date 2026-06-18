"""Regression guards for slim, consistent provider agent surfaces.

Two concerns:
1. The synthetic contributions stay slim — no duplicated prompt-tag doctrine,
   no removed blocks creeping back.
2. The tracked agent files (CLAUDE.md etc.) carry ONLY managed content, so every
   provider sees identical, generated instructions with no hand-edited drift.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import audiagentic.components.optional.providers  # noqa: F401
from audiagentic.components.optional.providers.surfaces.contributions import (
    build_summary_contributions,
    load_surface_contributions,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_AGENT_FILES = [
    "CLAUDE.md",
    "AGENTS.md",
    "COPILOT.md",
    "GEMINI.md",
    "QWEN.md",
    ".clinerules/audiagentic.md",
    ".roo/rules/audiagentic.md",
]

_HEADER = "<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->"
_BLOCK = re.compile(
    r"<!-- AUDIAGENTIC:BEGIN (?P<id>[^>]+?) -->.*?<!-- AUDIAGENTIC:END (?P=id) -->",
    re.DOTALL,
)
_REMOVED_IDS = (
    "agent-jobs/tag-shortcuts",
    "ag-review/review-doctrine",
    "agent-ledger/write-instruction",
)


# ── synthetic contributions stay slim ─────────────────────────────────────────

def test_summary_contributions_are_overview_and_canonical_only() -> None:
    ids = {c.contribution_id for c in build_summary_contributions()}
    assert "agent-jobs/overview" in ids
    assert "agent-jobs/canonical-rule" in ids
    assert "agent-jobs/tag-shortcuts" not in ids


def test_canonical_rule_does_not_duplicate_prompt_tag_doctrine() -> None:
    by_id = {c.contribution_id: c for c in load_surface_contributions()}
    canonical = by_id["agent-jobs/canonical-rule"].body.lower()
    # routing doctrine is owned by the prompt-tags block, not restated here
    assert "keep tag semantics identical" not in canonical
    assert "provenance" not in canonical


def test_removed_contributions_stay_removed() -> None:
    ids = {c.contribution_id for c in load_surface_contributions()}
    for gone in _REMOVED_IDS:
        assert gone not in ids, f"{gone} reappeared as a contribution"


# ── tracked agent files carry only managed content ────────────────────────────

def _existing_agent_files() -> list[Path]:
    return [_REPO_ROOT / rel for rel in _AGENT_FILES if (_REPO_ROOT / rel).exists()]


@pytest.mark.parametrize("path", _existing_agent_files(), ids=lambda p: p.name)
def test_agent_file_has_no_unmanaged_content(path: Path) -> None:
    """Every non-blank line is the managed header or inside a managed block."""
    text = path.read_text(encoding="utf-8")
    leftover = [
        line
        for line in _BLOCK.sub("", text).splitlines()
        if line.strip() and line.strip() != _HEADER
    ]
    assert not leftover, f"{path.name} has unmanaged content: {leftover[:3]}"


@pytest.mark.parametrize("path", _existing_agent_files(), ids=lambda p: p.name)
def test_agent_file_has_no_removed_blocks(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for gone in _REMOVED_IDS:
        assert f"BEGIN {gone}" not in text, f"{path.name} still has stale block {gone}"
