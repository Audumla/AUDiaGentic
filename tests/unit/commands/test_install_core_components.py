"""Install command must install every core component, and fail loud on failure."""
from __future__ import annotations

from types import SimpleNamespace

from audiagentic.commands import bootstrap as bootstrap_cmd


def _descriptors(monkeypatch, installed_ok: dict[str, bool]) -> None:
    descs = {
        "project": SimpleNamespace(core=True),
        "session": SimpleNamespace(core=True),
        "agent-planning": SimpleNamespace(core=False),  # non-core, must be skipped
    }
    monkeypatch.setattr(
        "audiagentic.foundation.components.loader.register_all_components", lambda: None
    )
    monkeypatch.setattr(
        "audiagentic.foundation.components.registry.all_descriptors", lambda: descs
    )
    installed: list[str] = []

    def _install(component_id, _project_root):
        installed.append(component_id)
        return {"ok": installed_ok.get(component_id, True)}

    monkeypatch.setattr(
        "audiagentic.foundation.lifecycle.components.install_component", _install
    )
    bootstrap_cmd._installed = installed  # type: ignore[attr-defined]


def test_installs_all_core_components_not_just_session(monkeypatch, tmp_path) -> None:
    _descriptors(monkeypatch, installed_ok={})
    failed = bootstrap_cmd._install_core_components(tmp_path)

    assert failed == []
    installed = bootstrap_cmd._installed  # type: ignore[attr-defined]
    assert set(installed) == {"project", "session"}
    assert "agent-planning" not in installed  # non-core never auto-installed


def test_reports_failed_core_component(monkeypatch, tmp_path) -> None:
    _descriptors(monkeypatch, installed_ok={"project": False})
    failed = bootstrap_cmd._install_core_components(tmp_path)
    assert failed == ["project"]


def test_cmd_bootstrap_fails_loud_when_core_component_fails(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(bootstrap_cmd, "install_to", lambda target, project_root=None: 0)
    monkeypatch.setattr(bootstrap_cmd, "_install_core_components", lambda _pr: ["project"])
    rc = bootstrap_cmd._cmd_bootstrap(tmp_path / "harness", tmp_path / "project")
    assert rc == 1
