"""Tests for the harness lifecycle event subscription (EV01).

The harness subscribes to lifecycle.component.* events at module import time.
On each event it refreshes its MCP config and logs the computed reload action.
No capability registration is involved — the harness reacts directly via
the event bus, following the surfaces/observer.py pattern.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from audiagentic.foundation.event import get_bus


def test_lifecycle_handler_reacts_to_installed_event(tmp_path: Path):
    """Handler calls refresh and logs action for installed events."""
    with patch(
        "audiagentic.runtime.harness.refresh_harness_config_if_installed",
        return_value=True,
    ) as mock_refresh:
        import audiagentic.runtime.harness  # noqa: F401

        bus = get_bus()
        bus.publish(
            "lifecycle.component.installed",
            {"component_id": "test-component", "project_root": tmp_path},
            metadata={"source_component": "lifecycle"},
        )

        mock_refresh.assert_called_once_with(
            tmp_path,
            reason="component-installed",
            component_id="test-component",
        )


def test_lifecycle_handler_disabled_event(tmp_path: Path):
    """Handler calls refresh with correct reason for disable events."""
    with patch(
        "audiagentic.runtime.harness.refresh_harness_config_if_installed",
        return_value=True,
    ) as mock_refresh:
        bus = get_bus()
        bus.publish(
            "lifecycle.component.disabled",
            {"component_id": "disable-test", "project_root": tmp_path},
            metadata={"source_component": "lifecycle"},
        )

        mock_refresh.assert_called_once_with(
            tmp_path,
            reason="component-disabled",
            component_id="disable-test",
        )


def test_lifecycle_handler_performs_config_refresh(tmp_path: Path):
    """Handler calls refresh_harness_config_if_installed on lifecycle events."""
    with patch(
        "audiagentic.runtime.harness.refresh_harness_config_if_installed",
        return_value=True,
    ) as mock_refresh:
        bus = get_bus()
        bus.publish(
            "lifecycle.component.installed",
            {"component_id": "refresh-test", "project_root": tmp_path},
            metadata={"source_component": "lifecycle"},
        )

        mock_refresh.assert_called_once_with(
            tmp_path,
            reason="component-installed",
            component_id="refresh-test",
        )


def test_lifecycle_handler_uninstalled_event(tmp_path: Path):
    """Handler calls refresh with correct reason for uninstall events."""
    with patch(
        "audiagentic.runtime.harness.refresh_harness_config_if_installed",
        return_value=True,
    ) as mock_refresh:
        bus = get_bus()
        bus.publish(
            "lifecycle.component.uninstalled",
            {"component_id": "uninstall-test", "project_root": tmp_path},
            metadata={"source_component": "lifecycle"},
        )

        mock_refresh.assert_called_once_with(
            tmp_path,
            reason="component-uninstalled",
            component_id="uninstall-test",
        )


def test_lifecycle_handler_enabled_event(tmp_path: Path):
    """Handler calls refresh with correct reason for enable events."""
    with patch(
        "audiagentic.runtime.harness.refresh_harness_config_if_installed",
        return_value=True,
    ) as mock_refresh:
        bus = get_bus()
        bus.publish(
            "lifecycle.component.enabled",
            {"component_id": "enable-test", "project_root": tmp_path},
            metadata={"source_component": "lifecycle"},
        )

        mock_refresh.assert_called_once_with(
            tmp_path,
            reason="component-enabled",
            component_id="enable-test",
        )


def test_lifecycle_status_messages_use_valid_gerunds(tmp_path: Path):
    """Refresh-only lifecycle status messages should not build words by suffix."""
    import audiagentic.runtime.harness as harness

    messages: list[str] = []

    with (
        patch("audiagentic.runtime.harness.refresh_harness_config_if_installed", return_value=True),
        patch("audiagentic.runtime.harness.push_status") as mock_push_status,
    ):
        mock_push_status.side_effect = lambda **kw: messages.append(kw["message"])

        harness._harness_lifecycle_handler(
            tmp_path,
            {"component_id": "plain-component"},
            {},
            reason="component-config-changed",
        )

    assert messages == ["Config refreshed after config change plain-component."]
    assert "config-changeding" not in messages[0]


def test_component_result_has_no_sync_field(tmp_path: Path):
    """Install/uninstall result no longer includes dead 'sync' field."""
    from audiagentic.foundation.lifecycle.components import _component_result

    result = _component_result(
        "test-component",
        reason="component-installed",
        extra_field="value",
    )

    assert "sync" not in result
    assert result["ok"] is True
    assert result["component_id"] == "test-component"
    assert result["extra_field"] == "value"


def test_component_mcp_module_removed():
    """component_mcp.py module was deleted as part of EV01."""
    import importlib

    try:
        importlib.import_module("audiagentic.foundation.lifecycle.component_mcp")
        raise AssertionError("component_mcp module should not exist")
    except ModuleNotFoundError:
        pass
