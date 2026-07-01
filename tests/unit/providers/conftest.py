"""Shared fixtures for unit/providers tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def claude_home(tmp_path: Path, monkeypatch) -> Path:
    """Redirect HOME so claude's ~/.claude/mcp.json lands inside tmp_path.

    Claude's MCP config path is '~/.claude/mcp.json' (global Claude Code config).
    Tests that call provider MCP functions for the claude provider must use this
    fixture to ensure writes land in an isolated temp directory.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home
