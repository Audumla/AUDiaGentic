"""Unit tests: harness reload marker classification and sync payload."""
from __future__ import annotations

import pytest

from audiagentic.runtime.harness.reload import _runtime_action_for_reason, build_runtime_sync


class TestRuntimeActionForReason:
    @pytest.mark.parametrize("reason", [
        "manual-refresh",
        "mcp-refresh-tool",
        "session-ui-visibility-updated",
    ])
    def test_always_reload_required_reasons(self, reason: str) -> None:
        assert _runtime_action_for_reason(reason, has_mcp_servers=False) == "reload_required"
        assert _runtime_action_for_reason(reason, has_mcp_servers=True) == "reload_required"

    @pytest.mark.parametrize("reason", [
        "component-installed",
        "component-uninstalled",
        "component-enabled",
        "component-disabled",
    ])
    def test_component_reason_with_mcp_servers_is_reload_required(self, reason: str) -> None:
        assert _runtime_action_for_reason(reason, has_mcp_servers=True) == "reload_required"

    @pytest.mark.parametrize("reason", [
        "component-installed",
        "component-uninstalled",
        "component-enabled",
        "component-disabled",
    ])
    def test_component_reason_without_mcp_servers_is_refresh_required(self, reason: str) -> None:
        assert _runtime_action_for_reason(reason, has_mcp_servers=False) == "refresh_required"

    def test_unknown_reason_is_refresh_required(self) -> None:
        assert _runtime_action_for_reason("some-other-reason") == "refresh_required"

    def test_default_has_mcp_servers_is_true(self) -> None:
        assert _runtime_action_for_reason("component-installed") == "reload_required"


class TestBuildRuntimeSync:
    def test_contains_required_keys(self) -> None:
        payload = build_runtime_sync(reason="manual-refresh", target="pi-runtime")
        assert "target" in payload
        assert "action" in payload
        assert "reason" in payload

    def test_target_passthrough(self) -> None:
        payload = build_runtime_sync(reason="manual-refresh", target="project")
        assert payload["target"] == "project"

    def test_component_id_included_when_given(self) -> None:
        payload = build_runtime_sync(reason="manual-refresh", target="pi-runtime", component_id="agent-ledger")
        assert payload["component_id"] == "agent-ledger"

    def test_component_id_absent_when_not_given(self) -> None:
        payload = build_runtime_sync(reason="manual-refresh", target="pi-runtime")
        assert "component_id" not in payload

    def test_component_with_mcp_emits_reload_required(self) -> None:
        payload = build_runtime_sync(reason="component-installed", target="project", has_mcp_servers=True)
        assert payload["action"] == "reload_required"

    def test_component_without_mcp_emits_refresh_required(self) -> None:
        payload = build_runtime_sync(reason="component-installed", target="project", has_mcp_servers=False)
        assert payload["action"] == "refresh_required"

    def test_reason_preserved_in_payload(self) -> None:
        payload = build_runtime_sync(reason="component-disabled", target="project")
        assert payload["reason"] == "component-disabled"
