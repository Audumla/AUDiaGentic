"""Tests for git_hooks_sync managed-block marker generation."""

from __future__ import annotations

from audiagentic.components.coding_lsp.git_hooks_sync import (
    _HOOK_BLOCK_ID,
    _hook_body_for_language,
)


def test_hook_block_markers_use_block_id_not_literal() -> None:
    """Opening and closing markers must interpolate _HOOK_BLOCK_ID — not use the literal string."""
    body = _hook_body_for_language("python-ruff", {"check": "ruff check"})

    # Opening marker uses f-string with _HOOK_BLOCK_ID
    assert f"# >>> audiagentic:{_HOOK_BLOCK_ID}:python-ruff >>>" in body
    # Closing marker also uses f-string with _HOOK_BLOCK_ID (not literal "_HOOK_BLOCK_ID")
    assert f"# <<< audiagentic:{_HOOK_BLOCK_ID}:language-hooks <<<" in body
    # Neither should contain the literal unexpanded string
    assert "_HOOK_BLOCK_ID" not in body
