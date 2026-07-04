"""Tests for the lifecycle→harness capability seam (AR19).

foundation/lifecycle never imports runtime/harness; it resolves the harness
through registered capabilities and no-ops gracefully when no harness is
active (headless installs, tests).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.capabilities import _REGISTRY
from audiagentic.foundation.components.base import ComponentDescriptor, McpServerDeclaration
from audiagentic.foundation.lifecycle.component_mcp import _refresh_mcp_config_if_needed
from audiagentic.foundation.lifecycle.components import _resolve_harness_sync


@pytest.fixture
def no_harness_capabilities():
    """Temporarily hide harness capabilities so tests exercise the absent path.

    runtime/harness registers them at import time; other tests may already
    have imported it, so remove-and-restore rather than assume absence.
    """
    saved = {k: _REGISTRY.pop(k) for k in list(_REGISTRY) if k.startswith("harness.")}
    yield
    # Drop any fakes the test registered, then restore what was there before.
    for key in [k for k in _REGISTRY if k.startswith("harness.")]:
        _REGISTRY.pop(key)
    _REGISTRY.update(saved)


def _descriptor_with_mcp() -> ComponentDescriptor:
    return ComponentDescriptor(
        component_id="sample",
        display_name="Sample",
        description="",
        detection_marker=".sample",
        mcp_servers=(
            McpServerDeclaration(name="ag-sample", module="audiagentic.components.sample.sample_mcp"),
        ),
    )


def test_resolve_harness_sync_noop_when_harness_absent(no_harness_capabilities):
    result = _resolve_harness_sync(reason="unit-test")
    assert result == {"skipped": "harness not active", "reason": "unit-test"}


def test_resolve_harness_sync_forwards_when_registered(no_harness_capabilities):
    calls: list[dict] = []
    _REGISTRY["harness.runtime-sync"] = lambda **kwargs: calls.append(kwargs) or {"ok": True}

    result = _resolve_harness_sync(reason="unit-test", component_id="sample", target="project")

    assert result == {"ok": True}
    assert calls == [{
        "reason": "unit-test",
        "component_id": "sample",
        "target": "project",
        "has_mcp_servers": True,
    }]


def test_mcp_config_refresh_noop_when_harness_absent(no_harness_capabilities, tmp_path: Path):
    # Must not raise or attempt any harness import when nothing is registered.
    _refresh_mcp_config_if_needed(_descriptor_with_mcp(), tmp_path, reason="unit-test")


def test_mcp_config_refresh_uses_registered_capability(no_harness_capabilities, tmp_path: Path):
    calls: list[tuple] = []
    _REGISTRY["harness.config-refresh"] = (
        lambda project_root, *, reason, component_id: calls.append((project_root, reason, component_id))
    )

    _refresh_mcp_config_if_needed(_descriptor_with_mcp(), tmp_path, reason="unit-test")

    assert calls == [(tmp_path, "unit-test", "sample")]


def test_harness_registers_capabilities_on_import():
    import audiagentic.runtime.harness  # noqa: F401
    from audiagentic.foundation.capabilities import get_capability

    assert get_capability("harness.runtime-sync") is not None
    assert get_capability("harness.config-refresh") is not None
