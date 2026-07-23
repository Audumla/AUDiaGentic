"""Focused result-boundary tests for the package updater."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from audiagentic.runtime.update import runner


def test_install_version_uses_downloaded_wheel_and_returns_success(tmp_path: Path) -> None:
    wheel = tmp_path / "audiagentic-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    completed = subprocess.CompletedProcess([], 0, "", "")

    with patch.object(runner, "_download_wheel", return_value=wheel) as download:
        with patch.object(runner, "_pip_install", return_value=completed) as install:
            assert runner.install_version("9.9.9") == {"ok": True, "version": "9.9.9"}

    download.assert_called_once()
    install.assert_called_once_with(wheel)


def test_install_version_returns_pip_failure(tmp_path: Path) -> None:
    wheel = tmp_path / "audiagentic-9.9.9-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    completed = subprocess.CompletedProcess([], 1, "", "pip failed")

    with patch.object(runner, "_download_wheel", return_value=wheel):
        with patch.object(runner, "_pip_install", return_value=completed):
            result = runner.install_version("9.9.9")

    assert result["ok"] is False
    assert "pip install failed" in result["error"]
