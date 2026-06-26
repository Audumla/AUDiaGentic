"""Integration test: launch embedded rig and test local_openai provider.

Uses the small test model at tests/unit/runtime/Qwen3.5-0.8B-UD-Q5_K_XL.gguf.

Run with: pytest tests/integration/runtime/test_ai_tester_integration.py -v
"""
from __future__ import annotations

import pathlib

import pytest

_test_model = pathlib.Path(__file__).parent.parent.parent / "unit" / "runtime" / "Qwen3.5-0.8B-UD-Q5_K_XL.gguf"

# Skip if the test model is missing.
if not _test_model.exists():
    pytest.skip("Test model not found at %s" % _test_model, allow_module_level=True)

# Skip if the llama-server binary is missing.
try:
    from audiagentic.runtime.rig.embedded.resolution import find_server_bin, runtime_bin_dir
    _bin_dir = runtime_bin_dir()
    find_server_bin(_bin_dir, None)
except Exception:  # noqa: BLE001
    pytest.skip("llama-server binary not found — provision rig/bin first", allow_module_level=True)


def test_local_openai_provider_with_real_rig():
    """Launch the embedded rig with qwen3.5-2b and call the local_openai adapter."""
    from audiagentic.components.providers.services.execution import execute_provider

    from ...unit.runtime.ai_tester import local_ai_tester

    with local_ai_tester(
        model_file=str(_test_model),
        port=42002,
        health_timeout=120.0,
    ) as tester:
        health = tester.health()
        assert health["status"] == "healthy", f"Rig unhealthy: {health}"

        provider_cfg = {
            "api-base-url": tester.endpoint.rsplit("/v1", 1)[0],
            "default-model": tester.model,
        }

        packet_ctx = {
            "job-id": "test-integration-001",
            "prompt-body": "What is 2+2? Answer with just the number.",
            "model-id": tester.model,
            "working-root": None,
            "stream-controls": {},
        }

        provider_cfg["stream"] = False

        result = execute_provider(
            provider_id="local-openai",
            packet_ctx=packet_ctx,
            provider_cfg=provider_cfg,
        )

        assert result["status"] == "ok", f"Provider failed: {result.get('output', '')[:200]}"
        assert "output" in result
        output = result["output"]
        assert output, f"Provider returned empty output. Full result: {result}"
        assert "4" in output or "two" in output.lower() or "answer" in output.lower(), (
            f"Unexpected response: {output[:200]}"
        )


def test_local_openai_chat_direct():
    """Launch the embedded rig and call chat() directly on the tester."""
    from ...unit.runtime.ai_tester import local_ai_tester

    with local_ai_tester(
        model_file=str(_test_model),
        port=42002,
        health_timeout=120.0,
    ) as tester:
        health = tester.health()
        assert health["status"] == "healthy"

        result = tester.chat("What is 1+1? Answer with just the number.")
        assert result.status == "ok", f"Chat failed: {result.error_message}"
        assert result.content, "Chat returned empty content"
        assert "2" in result.content, f"Expected '2' in response, got: {result.content[:200]}"


def test_local_openai_multiple_turns():
    """Test multiple sequential chat calls against the same rig instance."""
    from ...unit.runtime.ai_tester import local_ai_tester

    with local_ai_tester(
        model_file=str(_test_model),
        port=42002,
        health_timeout=120.0,
    ) as tester:
        health = tester.health()
        assert health["status"] == "healthy"

        r1 = tester.chat("Count from 1 to 3.")
        assert r1.status == "ok"

        r2 = tester.chat("Now count from 4 to 6.")
        assert r2.status == "ok"

        r3 = tester.chat("What is the sum of 1 through 6?")
        assert r3.status == "ok"
        assert "21" in r3.content, f"Expected '21' in response, got: {r3.content[:200]}"
