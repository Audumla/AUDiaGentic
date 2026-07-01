"""Regression tests for portable provider CLI probing.

Covers the Windows ``.CMD`` shim bug: npm/pip console-script shims are batch
files that ``CreateProcess`` cannot launch from a bare argv list, so a plain
``subprocess.run(["opencode", ...])`` raised ``WinError 2`` even though the tool
was installed.  Also guards the contract that a spawn failure reports
``available: False`` (a prior probe masked failures as available).
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

from audiagentic.components.providers.adapters import probe
from audiagentic.components.providers.adapters.probe import (
    probe_cli_version,
    run_cli,
)


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ── probe_cli_version contract ────────────────────────────────────────────────

def test_probe_missing_executable_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(probe.shutil, "which", lambda name: None)
    result = probe_cli_version("ghost", ["ghost", "--version"])
    assert result["available"] is False
    assert result["executable"] is None
    assert result["stderr"] == "command not found"


def test_probe_spawn_failure_reports_unavailable(monkeypatch) -> None:
    """Regression: a spawn error reports available=False, never True."""
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/path/to/tool")

    def boom(command, timeout=15.0):
        raise OSError("[WinError 2] The system cannot find the file specified")

    monkeypatch.setattr(probe, "run_cli", boom)
    result = probe_cli_version("tool", ["tool", "--version"])
    assert result["available"] is False
    assert "WinError 2" in result["stderr"]


def test_probe_success_captures_version(monkeypatch) -> None:
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/path/to/tool")
    monkeypatch.setattr(probe, "run_cli", lambda command, timeout=15.0: _FakeCompleted(0, "1.2.3"))
    result = probe_cli_version("tool", ["tool", "--version"])
    assert result["available"] is True
    assert result["returncode"] == 0
    assert result["stdout"] == "1.2.3"


def test_probe_nonzero_exit_reports_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(probe.shutil, "which", lambda name: "/path/to/tool")
    monkeypatch.setattr(probe, "run_cli", lambda command, timeout=15.0: _FakeCompleted(1, "", "boom"))
    result = probe_cli_version("tool", ["tool", "--version"])
    assert result["available"] is False


# ── run_cli behaviour ─────────────────────────────────────────────────────────

def test_run_cli_runs_command_cross_platform() -> None:
    completed = run_cli([sys.executable, "-c", "import sys; sys.stdout.write('hi')"])
    assert completed.returncode == 0
    assert "hi" in completed.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows .CMD shim behaviour")
def test_run_cli_executes_cmd_shim_that_bare_list_cannot(tmp_path, monkeypatch) -> None:
    """Regression: run_cli launches a .CMD shim that a bare argv list cannot.

    This is the exact npm ``opencode.CMD`` situation that produced WinError 2.
    """
    shim = tmp_path / "myshim.cmd"
    shim.write_text("@echo shim-ok\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    # bare argv list cannot launch the .CMD — the original bug
    with pytest.raises(FileNotFoundError):
        subprocess.run(["myshim"], capture_output=True, text=True, timeout=15)

    # run_cli routes through the shell and succeeds
    completed = run_cli(["myshim"])
    assert completed.returncode == 0
    assert "shim-ok" in completed.stdout


# ── descriptors delegate to the shared helper ─────────────────────────────────

def test_opencode_probe_delegates_to_shared_helper(monkeypatch) -> None:
    """Regression: opencode probe routes through probe_cli_version, not a bare run."""
    from audiagentic.components.providers.adapters.opencode import catalog as oc

    seen: dict[str, object] = {}

    def fake(name, command, **kwargs):
        seen["name"] = name
        seen["command"] = command
        return {"available": True}

    monkeypatch.setattr("audiagentic.components.providers.adapters.probe.probe_cli_version", fake)
    result = oc._opencode_probe(None)
    assert result["available"] is True
    assert seen["name"] == "opencode"
    assert seen["command"] == ["opencode", "--version"]
