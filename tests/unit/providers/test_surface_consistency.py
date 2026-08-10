"""Regression guards for slim, consistent provider agent surfaces.

Two concerns:
1. The synthetic contributions stay slim — no duplicated prompt-tag doctrine,
   no removed blocks creeping back.
2. The tracked agent files (CLAUDE.md etc.) keep provider/shared instruction
   text separate from the managed region and never regress to harness-only text.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import audiagentic.components.providers  # noqa: F401
from audiagentic.components.providers.surfaces.contributions import (
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
_REGION = re.compile(
    r"<!-- ag:managed:begin -->.*?<!-- ag:managed:end -->",
    re.DOTALL,
)
_REMOVED_IDS = (
    "agent-jobs/tag-shortcuts",
    "ag-review/review-doctrine",
    "agent-ledger/write-instruction",
)


# ── synthetic contributions stay slim ─────────────────────────────────────────

def test_summary_contributions_are_empty_without_action_tags() -> None:
    summary_ids = {c.contribution_id for c in build_summary_contributions()}
    assert summary_ids == set()
    assert "agent-jobs/overview" not in summary_ids

    # The jobs overview remains independent of deprecated action tags.
    all_ids = {c.contribution_id for c in load_surface_contributions()}
    assert "agent-jobs/overview" in all_ids
    assert "agent-jobs/tag-shortcuts" not in all_ids


def test_deprecated_prompt_tag_doctrine_is_not_projected() -> None:
    ids = {c.contribution_id for c in load_surface_contributions()}
    assert "agent-jobs/prompt-tags" not in ids


def test_removed_contributions_stay_removed() -> None:
    ids = {c.contribution_id for c in load_surface_contributions()}
    for gone in _REMOVED_IDS:
        assert gone not in ids, f"{gone} reappeared as a contribution"


# ── tracked agent files keep clean non-harness prefixes ───────────────────────

def _existing_agent_files() -> list[Path]:
    return [_REPO_ROOT / rel for rel in _AGENT_FILES if (_REPO_ROOT / rel).exists()]


@pytest.mark.parametrize("path", _existing_agent_files(), ids=lambda p: p.name)
def test_agent_file_has_no_harness_only_prompt_text(path: Path) -> None:
    """Provider surfaces must not carry harness-only provisioning prompt text."""
    text = path.read_text(encoding="utf-8")
    assert "You are the AUDiaGentic provisioning agent" not in text
    assert "This agent only handles AUDiaGentic provisioning via MCP tools." not in text
    assert "An MCP-only agent." not in text
    assert "You only act on requests that can be fulfilled using the MCP tools listed below." not in text


@pytest.mark.parametrize("path", _existing_agent_files(), ids=lambda p: p.name)
def test_agent_file_prefix_is_header_plus_optional_instruction_text(path: Path) -> None:
    """Outside managed region we keep only the file header and optional base instructions."""
    text = path.read_text(encoding="utf-8")
    leftover = _REGION.sub("", text).strip()
    if not leftover:
        return
    assert leftover.startswith(_HEADER)


@pytest.mark.parametrize("path", _existing_agent_files(), ids=lambda p: p.name)
def test_agent_file_has_single_wellformed_region(path: Path) -> None:
    """Exactly one managed region; no leftover legacy per-block fences."""
    text = path.read_text(encoding="utf-8")
    assert text.count("<!-- ag:managed:begin -->") == text.count("<!-- ag:managed:end -->")
    assert text.count("<!-- ag:managed:begin -->") <= 1
    assert "AUDIAGENTIC:BEGIN" not in text, f"{path.name} still has legacy per-block fences"
