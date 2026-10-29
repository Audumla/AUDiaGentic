from __future__ import annotations

import sys
from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system import managed_process
from audiagentic.foundation.system.managed_process import (
    DetachedLaunch,
    ProcessIdentity,
    command_fingerprint,
    current_process_evidence,
    launch_detached,
    observe_process,
    ownership_matches,
)
from audiagentic.foundation.system.managed_service_contracts import ProcessEvidence


def test_command_fingerprint_never_contains_raw_arguments() -> None:
    fingerprint = command_fingerprint(("gateway", "--token", "sensitive-value"))

    assert fingerprint.startswith("sha256:")
    assert "token" not in fingerprint
    assert "sensitive" not in fingerprint


def test_ownership_requires_pid_and_matching_non_pid_proof() -> None:
    evidence = ProcessEvidence(
        pid=42,
        scope="shared-service-host",
        command_fingerprint="sha256:expected",
        ownership_proof_kind="creation-identity",
        owner_epoch="epoch-a",
        creation_identity="created-a",
    )

    assert ownership_matches(evidence, ProcessIdentity(42, creation_identity="created-a"))
    assert not ownership_matches(evidence, ProcessIdentity(42, creation_identity="created-b"))
    assert not ownership_matches(evidence, ProcessIdentity(99, creation_identity="created-a"))
    assert not ownership_matches(evidence, ProcessIdentity(42))


def test_detached_launch_rejects_missing_working_directory(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError, match="VAL-MPROC-002"):
        DetachedLaunch(("gateway",), cwd=tmp_path / "missing")


def test_detached_launch_rejects_missing_log_file_directory(tmp_path: Path) -> None:
    with pytest.raises(AudiaGenticError, match="VAL-MPROC-006"):
        DetachedLaunch(("gateway",), log_file=tmp_path / "missing" / "service.log")


def test_launch_detached_without_log_file_still_redirects_to_devnull() -> None:
    assert DetachedLaunch(("gateway",)).log_file is None


def test_launch_detached_log_file_captures_real_child_stdout_and_stderr(tmp_path: Path) -> None:
    """SH31: a detached process's output must reach a real file, not DEVNULL."""
    log_path = tmp_path / "service.log"
    declaration = DetachedLaunch(
        (
            sys.executable, "-c",
            "import sys; print('stdout line'); print('stderr line', file=sys.stderr)",
        ),
        log_file=log_path,
    )
    launch_detached(declaration, owner_epoch="epoch-a")
    import time

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not (
        log_path.exists() and log_path.stat().st_size > 0
    ):
        time.sleep(0.05)
    content = log_path.read_text()
    assert "stdout line" in content
    assert "stderr line" in content


def test_current_process_evidence_has_observable_non_pid_proof() -> None:
    evidence = current_process_evidence(owner_epoch="epoch-current")

    assert evidence.owner_epoch == "epoch-current"
    assert ownership_matches(evidence, observe_process(evidence))


@pytest.mark.skipif(managed_process.os.name != "nt", reason="Windows job flags only")
def test_windows_breakaway_denial_is_observable_degraded_lifetime(monkeypatch) -> None:
    flags: list[int] = []

    class Process:
        pid = 4321

        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

    def popen(*_args, **kwargs):
        flags.append(kwargs["creationflags"])
        if len(flags) == 1:
            raise PermissionError("job denies breakaway")
        return Process()

    monkeypatch.setattr(managed_process.subprocess, "Popen", popen)
    monkeypatch.setattr(
        managed_process, "process_creation_identity", lambda _pid: "filetime:test"
    )

    evidence = launch_detached(DetachedLaunch(("gateway",)), owner_epoch="epoch-a")

    breakaway = managed_process.subprocess.CREATE_BREAKAWAY_FROM_JOB
    assert flags[0] & breakaway
    assert not flags[1] & breakaway
    assert evidence.scope == "session-child"
