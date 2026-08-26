"""Regression tests for component MCP stdio entry points."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("module_name", "bootstrap_name"),
    [
        ("runtime_mcp", "agents-runtime"),
        ("config_mcp", "agents-config"),
        ("admin_mcp", "agents-admin"),
    ],
)
def test_agents_mcp_main_passes_required_bootstrap_name(
    monkeypatch, module_name: str, bootstrap_name: str,
) -> None:
    """Generated Pi MCP launch entries must not exit before MCP initialize."""
    module = __import__(
        f"audiagentic.components.agents.mcp.{module_name}", fromlist=["main"],
    )
    observed: dict[str, object] = {}

    def fake_run(server, name):
        observed.update(server=server, name=name)

    monkeypatch.setattr(module, "run_mcp_server", fake_run)
    module.main()

    assert observed == {"server": module.mcp, "name": bootstrap_name}
