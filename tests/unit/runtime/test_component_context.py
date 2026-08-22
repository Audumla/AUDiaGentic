from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.components.base import ComponentDescriptor
from audiagentic.foundation.components.registry import register, reset
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime import component_context


def _registered_context_component(tmp_path: Path, *, component_id: str = "source-control") -> None:
    marker = tmp_path / ".audiagentic" / "components"
    marker.mkdir(parents=True)
    (marker / f"{component_id}.yaml").write_text("enabled: true\n", encoding="utf-8")
    register(
        ComponentDescriptor(
            component_id=component_id,
            display_name=component_id,
            description="",
            detection_marker=f".audiagentic/components/{component_id}.yaml",
            context_hook="test.context",
        )
    )


def test_collect_component_context_namespaces_and_redacts(tmp_path: Path, monkeypatch) -> None:
    reset()
    _registered_context_component(tmp_path)
    monkeypatch.setattr(
        component_context,
        "_resolve_context_hook",
        lambda _path: lambda _root: {"branch": "main", "api_key": "secret"},
    )

    assert component_context.collect_component_context(tmp_path) == {
        "source_control": {"branch": "main"}
    }


def test_collect_component_context_rejects_invalid_hook_result(tmp_path: Path, monkeypatch) -> None:
    reset()
    _registered_context_component(tmp_path)
    monkeypatch.setattr(component_context, "_resolve_context_hook", lambda _path: lambda _root: "bad")

    with pytest.raises(AudiaGenticError, match="must return a mapping"):
        component_context.collect_component_context(tmp_path)
