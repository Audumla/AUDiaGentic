"""Shared fixtures for unit/providers tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def claude_home(tmp_path: Path, monkeypatch) -> Path:
    """Redirect HOME for providers that still write to ~-scoped paths.

    Claude moved to project-local .mcp.json (CC55), so this fixture is retained
    only for other providers or legacy tests that need HOME redirected.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home
