from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_context_hook_resolution_is_runtime_owned() -> None:
    foundation_context = (
        ROOT / "src/audiagentic/foundation/components/context.py"
    ).read_text(encoding="utf-8")
    gateway_api = (
        ROOT / "src/audiagentic/components/agents/gateway/api.py"
    ).read_text(encoding="utf-8")
    runtime_context = (
        ROOT / "src/audiagentic/runtime/component_context.py"
    ).read_text(encoding="utf-8")

    assert "importlib" not in foundation_context
    assert "_resolve_context_hook" not in foundation_context
    assert "foundation.components.registry" not in foundation_context
    assert "runtime.component_context" not in gateway_api
    assert "def _resolve_context_hook" in runtime_context
