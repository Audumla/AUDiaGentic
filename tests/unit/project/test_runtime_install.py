"""The service runtime is a versioned, non-editable install switched by an atomic link."""
from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest

from audiagentic.components.project.runtime import install as runtime


def _wheel(tmp_path: Path, version: str = "1.2.3") -> Path:
    wheel = tmp_path / f"audiagentic-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("x.txt", version)
    return wheel


class FakeRunner:
    """Pretends to be uv and the venv python: creates the layout, can fail the health probe."""

    def __init__(self, *, fail_health: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fail_health = fail_health

    def __call__(self, command, **_kwargs):
        self.calls.append(command)
        if command[1:2] == ["venv"]:
            (Path(command[-1]) / "bin").mkdir(parents=True)
            (Path(command[-1]) / "bin" / "python").write_text("")
        if command[-2:-1] == ["-c"] and self.fail_health:
            return subprocess.CompletedProcess(command, 1, "", "ImportError: boom")
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.fixture(autouse=True)
def _uv(monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda name: f"/bin/{name}")


def test_install_creates_a_version_folder_and_switches_current_keeping_previous(tmp_path) -> None:
    root = tmp_path / "runtime"
    runner = FakeRunner()
    first = runtime.install(root, _wheel(tmp_path, "1.0.0"), runner=runner)
    assert (root / "current").is_symlink() and first["switched-from"] is None
    assert any("[acp,a2a]" in part for call in runner.calls for part in call)
    second = runtime.install(root, _wheel(tmp_path, "1.1.0"), runner=runner)
    assert second["switched-from"] == first["installed"]
    assert (root / "previous").resolve().name == first["installed"]
    assert (root / "current").resolve().name == second["installed"]


def test_a_failed_health_check_leaves_current_and_removes_the_half_built_version(tmp_path) -> None:
    root = tmp_path / "runtime"
    good = runtime.install(root, _wheel(tmp_path, "1.0.0"), runner=FakeRunner())
    with pytest.raises(runtime.RuntimeInstallError, match="boom"):
        runtime.install(root, _wheel(tmp_path, "2.0.0"), runner=FakeRunner(fail_health=True))
    assert (root / "current").resolve().name == good["installed"]
    assert [p.name for p in root.iterdir() if p.is_dir() and not p.is_symlink()] == [good["installed"]]


def test_rollback_swaps_current_and_previous_and_needs_a_previous(tmp_path) -> None:
    root = tmp_path / "runtime"
    first = runtime.install(root, _wheel(tmp_path, "1.0.0"), runner=FakeRunner())
    with pytest.raises(runtime.RuntimeInstallError, match="no previous"):
        runtime.rollback(root, runner=FakeRunner())
    second = runtime.install(root, _wheel(tmp_path, "1.1.0"), runner=FakeRunner())
    runtime.rollback(root, runner=FakeRunner())
    assert (root / "current").resolve().name == first["installed"]
    assert (root / "previous").resolve().name == second["installed"]


def test_an_absolute_seed_link_is_kept_as_previous_and_can_be_rolled_back_to(tmp_path) -> None:
    root, seed = tmp_path / "runtime", tmp_path / "seedvenv"
    (seed / "bin").mkdir(parents=True)
    (seed / "bin" / "python").write_text("")
    root.mkdir()
    (root / "current").symlink_to(seed)
    runtime.install(root, _wheel(tmp_path), runner=FakeRunner())
    assert (root / "previous").resolve() == seed.resolve()
    runtime.rollback(root, runner=FakeRunner())
    assert (root / "current").resolve() == seed.resolve()


def test_bad_inputs_are_refused_before_anything_is_created(tmp_path) -> None:
    with pytest.raises(runtime.RuntimeInstallError, match="not a wheel"):
        runtime.install(tmp_path / "runtime", tmp_path / "missing.whl", runner=FakeRunner())
    with pytest.raises(runtime.RuntimeInstallError, match="extras"):
        runtime.install(tmp_path / "runtime", _wheel(tmp_path), extras=["a;rm"], runner=FakeRunner())
    assert not (tmp_path / "runtime").exists()


def test_restart_request_needs_the_supervisor_folder(tmp_path) -> None:
    assert runtime.request_gateway_restart(tmp_path / "nope" / "x.restart") is False
    (tmp_path / "cmd").mkdir()
    assert runtime.request_gateway_restart(tmp_path / "cmd" / "x.restart") is True
    assert (tmp_path / "cmd" / "x.restart").exists()


def test_prune_keeps_current_previous_and_the_newest_and_skips_folders_in_use(tmp_path, monkeypatch) -> None:
    import os

    root = tmp_path / "runtime"
    root.mkdir()
    names = [f"1.{index}.0-aaaaaaa{index}" for index in range(6)]
    for index, name in enumerate(names):
        (root / name).mkdir()
        os.utime(root / name, (1000 + index, 1000 + index))
    (root / "current").symlink_to(names[1])     # old but live
    (root / "previous").symlink_to(names[0])
    (root / ".build").mkdir()
    monkeypatch.setattr("audiagentic.foundation.system.process.pids_referencing_path",
                        lambda path: [1] if path.name == names[2] else [])
    result = runtime.prune(root, keep=1)
    left = {p.name for p in root.iterdir() if p.is_dir() and not p.is_symlink()}
    assert left == {names[0], names[1], names[2], names[5]}   # pinned two, in use, newest one
    assert sorted(result["removed"]) == [names[3], names[4]]
    assert not (root / ".build").exists()
