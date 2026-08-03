from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from audiagentic.foundation.components import hooks
from audiagentic.foundation.contracts.errors import AudiaGenticError

# Status hooks are resolved by dotted path built from this module's ``__name__``.
# Under xdist with --import-mode=importlib the module identity a worker resolves
# depends on what it imported earlier, so these only hold in a dedicated process.
pytestmark = pytest.mark.no_parallel


@dataclass
class _Descriptor:
    component_id: str
    status_hook: str | None


def _valid_status(project_root: Path) -> hooks.ComponentStatusPayload:
    return hooks.ComponentStatusPayload(
        enabled=True,
        configured=True,
        active_implementation="local",
        missing_required=[],
        details={"path": str(project_root)},
    )


def _dict_status(project_root: Path) -> dict[str, object]:
    return {"enabled": True}


def _failing_status(project_root: Path) -> hooks.ComponentStatusPayload:
    raise RuntimeError("boom")


def test_get_component_status_serializes_payload(tmp_path: Path) -> None:
    descriptor = _Descriptor(__name__, f"{__name__}._valid_status")

    result = hooks.get_component_status(descriptor, tmp_path)

    assert result == {
        "enabled": True,
        "configured": True,
        "active_implementation": "local",
        "missing_required": [],
        "details": {"path": str(tmp_path)},
    }


def test_get_component_status_rejects_plain_dict(tmp_path: Path) -> None:
    descriptor = _Descriptor(__name__, f"{__name__}._dict_status")

    with pytest.raises(AudiaGenticError) as exc_info:
        hooks.get_component_status(descriptor, tmp_path)

    assert exc_info.value.code == "VAL-COMP-001"


def test_get_component_status_wraps_unhandled_hook_error(tmp_path: Path) -> None:
    descriptor = _Descriptor(__name__, f"{__name__}._failing_status")

    with pytest.raises(AudiaGenticError) as exc_info:
        hooks.get_component_status(descriptor, tmp_path)

    assert exc_info.value.code == "INT-COMP-002"
