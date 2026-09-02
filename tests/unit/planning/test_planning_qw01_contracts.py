"""Regression coverage for the QW01 planning MCP contract surface."""

from pathlib import Path
from typing import get_type_hints

import yaml

from audiagentic.components.planning import planning_manage_mcp
from audiagentic.components.planning.contracts import ConfigUpdates

_CONFIG = Path(__file__).parents[3] / "src" / "audiagentic" / "config" / "components" / "planning.yaml"


def _tool_descriptions() -> dict[str, str]:
    config = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    return {
        name: str(description)
        for server in config["mcp-servers"]
        for name, description in server.get("tool-descriptions", {}).items()
    }


def test_planning_config_exposes_exactly_nineteen_tools():
    config = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    assert sum(len(server["direct-tools"]) for server in config["mcp-servers"]) == 19


def test_agent_descriptions_are_concise_and_current():
    descriptions = _tool_descriptions()
    assert len(descriptions) == 19
    assert all(len(description) <= 180 for description in descriptions.values())
    assert "work is optional" in config_text()
    assert "provide plan or id_prefix" in descriptions["plan_list_items"]


def config_text() -> str:
    return _CONFIG.read_text(encoding="utf-8")


def test_config_wrapper_uses_open_typed_contract():
    assert get_type_hints(planning_manage_mcp.planning_set_config)["updates"] is ConfigUpdates
