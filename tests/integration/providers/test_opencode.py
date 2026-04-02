"""opencode provider adapter tests."""

from __future__ import annotations

from audiagentic.execution.providers.adapters.opencode import run


def test_adapter_returns_scaffolded_result() -> None:
    result = run({"provider-id": "opencode", "cwd": "."}, {})
    assert result["provider-id"] == "opencode"
    assert result["provider"] == "opencode"
    assert result["status"] == "scaffolded"
