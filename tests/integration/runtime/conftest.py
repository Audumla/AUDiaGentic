"""Override the home isolation fixture for integration rig tests.

Integration tests that launch the embedded rig need the real global home,
not the temp directory that the root conftest creates.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _use_real_audiagentic_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the real _AUDIAGENTIC_HOME instead of isolating to a temp dir.

    The repo-root override is set per test (never at import time): an import-time assignment leaked
    into every other test collected in the same process.
    """
    from audiagentic.foundation.paths.names import home_directory

    monkeypatch.setenv("_AUDIAGENTIC_HOME", str(home_directory()))
    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", "C:\\")
