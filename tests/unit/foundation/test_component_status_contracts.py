from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.configuration import management as agents_api
from audiagentic.components.coding_lsp import coding_lsp_bootstrap
from audiagentic.components.memory import memory_api
from audiagentic.components.planning import planning_api
from audiagentic.components.source_control import source_control_bootstrap
from audiagentic.foundation.components import is_enabled
from audiagentic.foundation.components.loader import register_all_components
from audiagentic.foundation.features.registry import clear as clear_features

EXPECTED_KEYS = {
    "enabled",
    "configured",
    "active_implementation",
    "missing_required",
    "details",
}


def _fresh_registry() -> None:
    clear_features()
    register_all_components()


def test_memory_status_contract(tmp_path: Path) -> None:
    _fresh_registry()

    payload = memory_api.memory_status(tmp_path).to_dict()

    assert set(payload) == EXPECTED_KEYS
    # top-level `enabled` is component-level, not implementation-level — see
    # docs/standards/CREATING_A_COMPONENT.md §11. Implementation-level state is reported
    # separately so it can't be confused with the component's own enabled flag.
    assert payload["enabled"] == is_enabled("memory", tmp_path)
    assert {"enabled", "is_default"} <= set(payload["details"]["implementation"])


def test_planning_status_contract(tmp_path: Path) -> None:
    _fresh_registry()

    payload = planning_api.planning_status(tmp_path).to_dict()

    assert set(payload) == EXPECTED_KEYS
    assert "pending_items" in payload["details"]
    assert "completed_items" in payload["details"]
    assert "implementation" not in payload
    assert payload["enabled"] == is_enabled("agent-planning", tmp_path)
    assert {"enabled", "is_default"} <= set(payload["details"]["implementation"])


def test_source_control_status_contract(tmp_path: Path) -> None:
    _fresh_registry()

    payload = source_control_bootstrap.status_payload(tmp_path).to_dict()

    assert set(payload) == EXPECTED_KEYS
    assert "mcp_servers" in payload["details"]
    assert "mcp-servers" not in payload


def test_coding_lsp_status_contract_when_no_dependencies(tmp_path: Path, monkeypatch) -> None:
    _fresh_registry()
    monkeypatch.setattr(coding_lsp_bootstrap, "_active_dependency_ids", lambda project_root: [])

    payload = coding_lsp_bootstrap.status_payload(tmp_path).to_dict()

    assert set(payload) == EXPECTED_KEYS
    assert payload["configured"] is True
    assert payload["missing_required"] == []


def test_agents_status_contract(tmp_path: Path) -> None:
    _fresh_registry()

    payload = agents_api.agent_status(tmp_path).to_dict()

    assert set(payload) == EXPECTED_KEYS
    assert payload["active_implementation"] is None  # agents has no implementation concept
    assert payload["enabled"] == is_enabled("agents", tmp_path)
    assert "profile_count" in payload["details"]
    assert "gateway" in payload["details"]
