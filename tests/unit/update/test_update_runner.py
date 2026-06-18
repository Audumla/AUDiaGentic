"""Regression tests for runtime/update/runner.py error paths."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from audiagentic.runtime.update import runner


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="_schedule_post_exit_install uses Windows-only subprocess creationflags",
)
def test_schedule_post_exit_install_spawn_failure_returns_error(tmp_path: Path) -> None:
    """Regression: a spawn failure returns an error dict, not a NameError.

    The except block interpolates the exception into the error string; without
    binding (`except Exception as exc`) the failure path itself raised NameError
    instead of reporting why the updater could not be spawned.
    """
    wheel = tmp_path / "audiagentic-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"")

    with patch.object(runner.subprocess, "Popen", side_effect=OSError("spawn boom")):
        result = runner._schedule_post_exit_install(wheel, "9.9.9")

    assert result["ok"] is False
    assert "could not spawn updater" in result["error"]
    assert "spawn boom" in result["error"]
    # the temp PS1 script is cleaned up on failure
    assert not (wheel.parent / "_audiagentic_update.ps1").exists()
