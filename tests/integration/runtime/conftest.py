"""Override the home isolation fixture for integration rig tests.

Integration tests that launch the embedded rig need the real global home,
not the temp directory that the root conftest creates.
"""
from __future__ import annotations

import os
import pathlib

import pytest

_real_home = pathlib.Path.home() / ".audiagentic"
os.environ["AUDIAGENTIC_HOME"] = str(_real_home)
os.environ["AUDIAGENTIC_REPO_ROOT"] = "C:\\"


@pytest.fixture(autouse=True)
def _use_real_audiagentic_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real AUDIAGENTIC_HOME instead of isolating to a temp dir."""
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(_real_home))
