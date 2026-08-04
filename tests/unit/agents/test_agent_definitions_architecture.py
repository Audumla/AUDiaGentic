"""AS62 architecture invariants for Agent Definition.

Checked by source inspection, per this repo's established pattern (see
foundation/composition's and Role's own architecture tests): a boundary
violation is a defect a passing behavioural test would not notice.
"""
from __future__ import annotations

from audiagentic.foundation.paths.package import PACKAGE_ROOT

_MODEL_MODULE = PACKAGE_ROOT / "components" / "agents" / "models" / "agent_definition.py"
_API_MODULE = PACKAGE_ROOT / "components" / "agents" / "models" / "agent_definition_api.py"


def test_agent_definition_domain_code_imports_no_concrete_store_or_composition() -> None:
    """Agent Definition storage is deliberately not composed (RV890) -- neither
    module performs a foundation-composition graph lookup."""
    for module in (_MODEL_MODULE, _API_MODULE):
        text = module.read_text(encoding="utf-8")
        assert "audiagentic.foundation.composition" not in text
        assert ".root(" not in text
        assert "get_gateway_registry" not in text


def test_agent_definition_code_imports_no_mcp_or_provider_adapter_modules() -> None:
    """Publication flags do not alter runtime MCP projection: neither module
    imports MCP server machinery or provider-native adapter internals to make
    that claim mechanically checkable, not just asserted in prose. `acp`/`a2a`
    are stored as plain bool flags (field names), not protocol implementations,
    so this checks imports rather than the substring "mcp"/"acp"."""
    for module in (_MODEL_MODULE, _API_MODULE):
        for line in module.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert "mcp" not in stripped.lower(), f"{module.name}: {stripped}"
                assert "audiagentic.components.providers.adapters" not in stripped, (
                    f"{module.name}: {stripped}"
                )


def test_agent_definition_has_no_provider_native_or_protocol_fields() -> None:
    """Acceptance criteria: no snapshot objects, protocol types, or
    provider-native data in the model -- only IDs and simple scalars."""
    from audiagentic.components.agents.models.agent_definition import (
        AgentDefinition,
    )

    fields = set(AgentDefinition.__dataclass_fields__)
    forbidden = {
        "provider_id", "model_id", "model_alias", "params",
        "session_surface", "mcp_servers", "runtime_tools", "permissions",
        "version", "generation",
    }
    assert fields & forbidden == set()
