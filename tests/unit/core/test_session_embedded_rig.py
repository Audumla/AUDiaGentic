from __future__ import annotations

from pathlib import Path

from audiagentic.components.core.session.session_embedded_rig import (
    _update_global_embedded_rig_impl,
)


def test_update_global_embedded_rig_impl_reports_project_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness_runtime = tmp_path / "home" / "harness"
    global_bin_dir = harness_runtime / "rig" / "bin"
    global_bin_dir.mkdir(parents=True)
    project_bin_dir = tmp_path / "project" / ".audiagentic" / "provisioning" / "rig" / "embedded" / "bin"
    project_bin_dir.mkdir(parents=True)

    calls: list[Path] = []
    events: list[str] = []

    def _fake_update(*, runtime_dir=None, target_bin_dir=None):
        calls.append(target_bin_dir)
        print("Installed global llama-server")

    def _sink(event) -> None:
        events.append(event.message)

    monkeypatch.setattr(
        "audiagentic.runtime.rig.embedded.binaries.update_binaries",
        _fake_update,
    )
    monkeypatch.setattr(
        "audiagentic.runtime.rig.embedded.launch.runtime_bin_dir",
        lambda: project_bin_dir,
    )

    result = _update_global_embedded_rig_impl(harness_runtime, sink=_sink)

    assert result["ok"] is True
    assert calls == [global_bin_dir]
    assert result["global_active"] is False
    assert result["project_local_overrides_global"] is True
    assert any("project-local embedded rig binary still takes precedence" in message for message in events)


def test_update_global_embedded_rig_impl_reports_global_active(
    tmp_path: Path,
    monkeypatch,
) -> None:
    harness_runtime = tmp_path / "home" / "harness"
    global_bin_dir = harness_runtime / "rig" / "bin"
    global_bin_dir.mkdir(parents=True)

    monkeypatch.setattr(
        "audiagentic.runtime.rig.embedded.binaries.update_binaries",
        lambda *, runtime_dir=None, target_bin_dir=None: print("Installed global llama-server"),
    )
    monkeypatch.setattr(
        "audiagentic.runtime.rig.embedded.launch.runtime_bin_dir",
        lambda: global_bin_dir,
    )

    result = _update_global_embedded_rig_impl(harness_runtime, sink=None)

    assert result["ok"] is True
    assert result["global_active"] is True
    assert result["project_local_overrides_global"] is False
