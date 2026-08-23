from __future__ import annotations

from pathlib import Path

from audiagentic.components.project import project_components
from audiagentic.foundation.components import registry
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_empty_component_marker_is_disabled_not_an_exception(tmp_path: Path) -> None:
    class _Marker:
        def exists(self) -> bool:
            return True

    # A legacy empty marker loads as None.  The registry must not call .get()
    # on it while servicing a status read.
    from pytest import MonkeyPatch

    monkeypatch = MonkeyPatch()
    monkeypatch.setattr(registry, "marker_path", lambda *_args: _Marker())
    monkeypatch.setattr(registry, "load_yaml_file", lambda _path: None)
    try:
        assert registry.is_enabled("source-control", tmp_path) is False
        assert registry.get_external_probe_results("source-control", tmp_path) == {}
    finally:
        monkeypatch.undo()


def test_component_listing_keeps_other_components_when_a_status_hook_fails(
    tmp_path: Path, monkeypatch
) -> None:
    def failing_status(descriptor, project_root: Path):
        if descriptor.component_id == "source-control":
            raise AudiaGenticError(
                code="INT-COMP-002",
                kind="components",
                message="component status hook failed",
                details={"component_id": "source-control"},
            )
        return None

    monkeypatch.setattr(project_components, "is_installed", lambda _id, _root: True)
    monkeypatch.setattr(project_components, "is_enabled", lambda _id, _root: True)
    monkeypatch.setattr(project_components, "get_component_status", failing_status)

    rows = project_components.list_components(tmp_path)
    source_control = next(row for row in rows if row["component_id"] == "source-control")

    assert source_control["component_status_error"] == {
        "code": "INT-COMP-002",
        "kind": "components",
        "message": "component status hook failed",
        "details": {"component_id": "source-control"},
    }
    assert any(row["component_id"] == "project" for row in rows)
