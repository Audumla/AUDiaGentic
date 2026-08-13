from __future__ import annotations

from audiagentic.components.agents.mcp.gateway_mcp import _sparse


def test_gateway_mcp_payloads_omit_absent_values_and_keep_false_zero() -> None:
    assert _sparse(
        {
            "request-id": "req-1",
            "session-id": None,
            "metadata": {},
            "provider-metadata": {"chat-url": "", "live": False, "attempt": 0},
            "items": [{"value": None}, {"value": "kept"}],
        }
    ) == {
        "request-id": "req-1",
        "provider-metadata": {"live": False, "attempt": 0},
        "items": [{"value": "kept"}],
    }

