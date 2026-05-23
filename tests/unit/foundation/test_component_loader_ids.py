from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.components.base import ComponentDescriptor
from audiagentic.foundation.components.loader import (
    _validate_loaded_descriptors,
    register_from_yaml,
)


def _write_component(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _descriptor(component_id: str, *, depends_on: tuple[str, ...] = ()) -> ComponentDescriptor:
    return ComponentDescriptor(
        component_id=component_id,
        display_name=component_id,
        description="",
        detection_marker=f".audiagentic/components/{component_id}.yaml",
        depends_on=depends_on,
    )


def test_component_descriptor_requires_id(tmp_path: Path) -> None:
    path = tmp_path / "missing-id.yaml"
    _write_component(path, "type: component\ncontract-version: v1\n")

    with pytest.raises(ValueError, match="missing or empty id"):
        register_from_yaml(path)


def test_loaded_components_reject_duplicate_ids() -> None:
    with pytest.raises(ValueError, match="duplicate component ids"):
        _validate_loaded_descriptors([_descriptor("one"), _descriptor("one")])


def test_loaded_components_reject_unknown_dependency() -> None:
    with pytest.raises(ValueError, match="depends on unknown component"):
        _validate_loaded_descriptors([_descriptor("one", depends_on=("missing",))])
