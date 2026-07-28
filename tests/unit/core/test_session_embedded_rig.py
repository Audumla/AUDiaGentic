from __future__ import annotations

from pathlib import Path

from audiagentic.components.session.session_embedded_rig import (
    _update_global_embedded_rig_impl,
    embedded_rig_upgrade_status,
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

    def _fake_recipe(target_bin_dir):
        calls.append(target_bin_dir)
        return type("Recipe", (), {"upgrade": lambda self, _ctx: type("Result", (), {"success": True})()})()

    def _sink(event) -> None:
        events.append(event.message)

    monkeypatch.setattr(
        "audiagentic.runtime.rig.embedded.recipe.llama_cpp_recipe",
        _fake_recipe,
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
        "audiagentic.runtime.rig.embedded.recipe.llama_cpp_recipe",
        lambda _target: type("Recipe", (), {"upgrade": lambda self, _ctx: type("Result", (), {"success": True})()})(),
    )
    monkeypatch.setattr(
        "audiagentic.runtime.rig.embedded.launch.runtime_bin_dir",
        lambda: global_bin_dir,
    )

    result = _update_global_embedded_rig_impl(harness_runtime, sink=None)

    assert result["ok"] is True
    assert result["global_active"] is True
    assert result["project_local_overrides_global"] is False


def test_embedded_rig_upgrade_status_is_read_only_and_explicit(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "rig" / "bin"
    calls: list[Path] = []

    class Recipe:
        def upgrade_status(self, _context):
            return type("Result", (), {
                "success": True,
                "state": type("State", (), {"value": "upgrade-available"})(),
                "status": "pinned release differs",
                "details": {"declared-version": "b9204"},
            })()

    monkeypatch.setattr(
        "audiagentic.runtime.rig.embedded.recipe.llama_cpp_recipe",
        lambda target_bin_dir: calls.append(target_bin_dir) or Recipe(),
    )
    monkeypatch.setattr(
        "audiagentic.runtime.rig.embedded.launch.runtime_bin_dir", lambda: target
    )

    result = embedded_rig_upgrade_status(scope="local")

    assert result["ok"] is True
    assert result["state"] == "upgrade-available"
    assert calls == [target]
