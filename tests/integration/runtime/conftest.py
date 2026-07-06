"""Override the home isolation fixture for integration rig tests.

Integration tests that launch the embedded rig need the real global home,
not the temp directory that the root conftest creates.
"""
from __future__ import annotations

import os

import pytest

os.environ["AUDIAGENTIC_REPO_ROOT"] = "C:\\"


@pytest.fixture(autouse=True)
def _use_real_audiagentic_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real AUDIAGENTIC_HOME instead of isolating to a temp dir."""
    from audiagentic.foundation.paths.names import home_directory

    monkeypatch.setenv("AUDIAGENTIC_HOME", str(home_directory()))
