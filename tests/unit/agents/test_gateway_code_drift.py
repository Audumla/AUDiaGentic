"""A running gateway older than the code on disk is reported, never acted on."""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from audiagentic.components.agents.configuration import doctor_checks
from audiagentic.components.agents.gateway.service import code_drift
from audiagentic.foundation.lifecycle.doctor import OK, WARN


class _Store:
    def __init__(self, state="running", pid=4242) -> None:
        self._record = SimpleNamespace(state=state, process=SimpleNamespace(pid=pid) if pid else None)

    def read(self):
        return self._record


def _package(tmp_path: Path, mtime: float) -> Path:
    root = tmp_path / "pkg"
    (root / "sub").mkdir(parents=True, exist_ok=True)
    source = root / "sub" / "mod.py"
    source.write_text("x = 1\n")
    os.utime(source, (mtime, mtime))
    return root


def _compare(tmp_path, *, started, changed, **kwargs):
    return code_drift.check_gateway_code_drift(
        store=kwargs.pop("store", _Store()), package_root=_package(tmp_path, changed),
        start_epoch=lambda _pid: started, **kwargs)


def test_code_changed_after_the_service_started_is_drift(tmp_path) -> None:
    drift = _compare(tmp_path, started=1_000_000.0, changed=1_000_600.0)
    assert drift.status == "drift" and "sub/mod.py" in drift.detail and drift.pid == 4242


def test_service_started_after_the_last_change_is_fine(tmp_path) -> None:
    assert _compare(tmp_path, started=1_000_600.0, changed=1_000_000.0).status == "ok"
    assert _compare(tmp_path, started=1_000_000.0, changed=1_000_003.0).status == "ok"  # inside the grace window


def test_unreadable_start_time_or_unknown_installation_is_unknown_not_drift(tmp_path) -> None:
    assert _compare(tmp_path, started=None, changed=1.0).status == "unknown"
    drift = code_drift.check_gateway_code_drift(store=_Store(), start_epoch=lambda _pid: 1_000_000.0,
                                                package_root_for=lambda _pid: None)
    assert drift.status == "unknown" and "cannot be determined" in drift.detail


def test_installation_is_asked_of_the_services_own_interpreter() -> None:
    # this process's command line starts with an interpreter that can import the package
    root = code_drift.service_package_root(os.getpid())
    if Path("/proc/self/cmdline").exists():
        assert root is not None and (root / "__init__.py").is_file()


def test_no_service_means_nothing_to_compare(tmp_path) -> None:
    class Missing:
        def read(self):
            raise FileNotFoundError

    assert _compare(tmp_path, started=1.0, changed=2.0, store=Missing()).status == "ok"
    assert _compare(tmp_path, started=1.0, changed=2.0, store=_Store(state="stopped", pid=0)).status == "ok"


def test_start_time_comes_from_proc_for_this_process() -> None:
    started = code_drift.process_start_epoch(os.getpid())
    if not Path("/proc/self/stat").exists():
        assert started is None
        return
    import time

    assert started is not None and 0 < time.time() - started < 7 * 86400 * 52


def test_doctor_check_reports_a_warning_with_a_fix_only_for_drift(monkeypatch) -> None:
    monkeypatch.setattr(code_drift, "check_gateway_code_drift", lambda: code_drift.Drift("drift", "mod.py changed", 7))
    [result] = doctor_checks.check_gateway_code_drift(SimpleNamespace())
    assert result.status == WARN and "restart" in result.fix.lower()
    monkeypatch.setattr(code_drift, "check_gateway_code_drift", lambda: code_drift.Drift("unknown", "no /proc"))
    assert doctor_checks.check_gateway_code_drift(SimpleNamespace())[0].status == OK


def _repo(tmp_path: Path) -> Path:
    import subprocess

    def git(*args: str, when: int) -> None:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
               "GIT_COMMITTER_DATE": f"@{when} +0000", "GIT_AUTHOR_DATE": f"@{when} +0000"}
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, env=env)

    package = tmp_path / "src" / "pkg"
    package.mkdir(parents=True)
    git("init", "-q", when=1_000_000)
    (package / "mod.py").write_text("x = 1\n")
    git("add", ".", when=1_000_000)
    git("commit", "-q", "-m", "a", when=1_000_000)
    (package / "mod.py").write_text("x = 2\n")
    git("commit", "-q", "-am", "b", when=1_000_600)
    return package


def test_a_checkout_moved_after_the_start_is_drift_by_commit(tmp_path) -> None:
    package = _repo(tmp_path)
    drift = code_drift.check_gateway_code_drift(store=_Store(), package_root=package,
                                                start_epoch=lambda _pid: 1_000_300.0)
    assert drift.status == "drift" and "loaded" in drift.detail


def test_same_commit_is_fine_even_when_file_timestamps_are_newer(tmp_path) -> None:
    package = _repo(tmp_path)
    later = 2_000_000_000
    os.utime(package / "mod.py", (later, later))  # a checkout round trip rewrites mtimes, not content
    drift = code_drift.check_gateway_code_drift(store=_Store(), package_root=package,
                                                start_epoch=lambda _pid: 1_000_700.0)
    assert drift.status == "ok"


def test_tracked_edit_after_the_start_is_drift_and_missing_reflog_is_unknown(tmp_path) -> None:
    package = _repo(tmp_path)
    (package / "mod.py").write_text("x = 3\n")  # uncommitted edit, mtime is now
    edited = code_drift.check_gateway_code_drift(store=_Store(), package_root=package,
                                                 start_epoch=lambda _pid: 1_000_700.0)
    assert edited.status == "drift" and "edited" in edited.detail
    before_history = code_drift.check_gateway_code_drift(store=_Store(), package_root=package,
                                                         start_epoch=lambda _pid: 500.0)
    assert before_history.status == "unknown"
