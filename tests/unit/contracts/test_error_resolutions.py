"""Tests for error resolution loading and lookup."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.contracts.error_resolutions import (
    load_all_error_resolutions,
    load_error_resolutions_from_component,
)
from audiagentic.foundation.contracts.errors import (
    AudiaGenticError,
    _mark_error_resolutions_loaded,
    get_error_resolution,
    register_error_resolution,
)


def test_get_error_resolution_returns_registered() -> None:
    register_error_resolution("TEST-001", "test resolution")
    assert get_error_resolution("TEST-001") == "test resolution"


def test_get_error_resolution_returns_none_for_unregistered() -> None:
    assert get_error_resolution("NONEXISTENT-001") is None


def test_load_all_error_resolutions_populates_registry() -> None:
    config_dirs = [Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"]
    load_all_error_resolutions(config_dirs)

    assert get_error_resolution("VAL-PPARSE-001") is not None
    assert get_error_resolution("VAL-COMPLETE-001") is not None
    assert get_error_resolution("VAL-SESSVIS-001") is not None
    assert get_error_resolution("CON-ARCHIVE-001") is not None
    assert get_error_resolution("IO-JOBSTORE-001") is not None
    assert get_error_resolution("VAL-PROJFILE-001") is not None


def test_load_error_resolutions_from_component_returns_count() -> None:
    config_dir = Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"
    count = load_error_resolutions_from_component("project", config_dir)
    assert count == 6


def test_unregistered_error_code_blocked_after_load() -> None:
    """After load_all_error_resolutions, an unregistered code raises ValueError."""
    _mark_error_resolutions_loaded()
    with pytest.raises(ValueError, match="not registered"):
        AudiaGenticError(
            code="VAL-UNKNOWN-001",
            kind="providers",
            message="this code is not registered",
        )


def test_registered_error_code_allowed_after_load() -> None:
    """A registered code can still be instantiated after load."""
    config_dirs = [Path(__file__).resolve().parents[3] / "src" / "audiagentic" / "config" / "components"]
    load_all_error_resolutions(config_dirs)
    err = AudiaGenticError(
        code="VAL-PCFG-001",
        kind="providers",
        message="provider config failed validation",
    )
    assert err.code == "VAL-PCFG-001"
