"""Redacted-serialization tests for overseer research artifacts.

Verifies that the _redact_result helper in run_gateway_request.py strips
prompt-body, output text, and completion stdout from persisted results, and
that bounded wait/status paths are exercised with a fake gateway client.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from audiagentic.components.agents.agents_gateway_client import (
    GatewayClient,
)


def _load_redact_helper():
    """Load _redact_result from the research helper script by path."""
    script = _ROOT / ".audiagentic" / "research" / "agent-overseer" / "run_gateway_request.py"
    spec = importlib.util.spec_from_file_location("run_gateway_request", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeGatewayClient(GatewayClient):
    """Minimal fake gateway client for bounded wait/status tests."""

    def __init__(self) -> None:
        self._requests: dict[str, dict] = {}

    def submit_llm_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        request_id = kwargs.get("metadata", {}).get("subject") or "req_fake"
        record = {
            "request-id": request_id,
            "state": "queued",
            "prompt-body": kwargs.get("prompt_body", ""),
            **kwargs,
        }
        self._requests[request_id] = record
        return {"request-id": request_id, "state": "queued"}

    def get_llm_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        return self._requests.get(request_id, {"error": "not found"})

    def wait_llm_request(
        self, project_root: Path, request_id: str, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        record = self._requests.get(request_id)
        if not record:
            return {"error": "not found"}
        return record

    def cancel_llm_request(self, project_root: Path, request_id: str) -> dict[str, Any]:
        record = self._requests.get(request_id)
        if record:
            record["state"] = "cancelled"
        return {"request-id": request_id, "state": "cancelled"}

    def run_llm_request(self, project_root: Path, **kwargs: Any) -> dict[str, Any]:
        """Simulate a completed blocking run."""
        return {
            "state": "completed",
            "prompt-body": kwargs.get("prompt_body", ""),
            "output": "fake output text that should be redacted",
            "completion": {
                "stdout": "fake stdout that should be redacted",
                "status": "ok",
            },
            **kwargs,
        }

    def list_llm_requests(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self._requests.values())

    def gateway_overview(self, project_root: Path) -> dict[str, Any]:
        return {"queue-depths": {}}

    def list_llm_sessions(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def close_llm_session(self, project_root: Path, session_id: str) -> dict[str, Any]:
        return {"session-id": session_id, "state": "closed"}


def test_redact_removes_prompt_body_and_output() -> None:
    """_redact_result removes prompt-body and output from persisted result."""
    mod = _load_redact_helper()
    redact = getattr(mod, "_redact_result")

    raw = {
        "state": "completed",
        "prompt-body": "secret instructions",
        "output": "raw model output",
        "completion": {"stdout": "model stdout", "status": "ok"},
    }

    redacted = redact(raw)

    assert "prompt-body" not in redacted
    assert "output" not in redacted or redacted.get("output") is None
    completion = redacted.get("completion", {})
    assert "stdout" not in completion


def test_redact_preserves_non_sensitive_fields() -> None:
    """_redact_result keeps state, provider-id, and other metadata."""
    mod = _load_redact_helper()
    redact = getattr(mod, "_redact_result")

    raw = {
        "state": "completed",
        "provider-id": "opencode",
        "request-id": "req_123",
        "prompt-body": "secret",
        "output": "raw output",
        "completion": {"stdout": "model stdout", "status": "ok", "stop_reason": "end_turn"},
    }

    redacted = redact(raw)

    assert redacted["state"] == "completed"
    assert redacted["provider-id"] == "opencode"
    assert redacted["request-id"] == "req_123"
    completion = redacted.get("completion", {})
    assert completion.get("stop_reason") == "end_turn"


def test_fake_client_submit_and_wait_bounded() -> None:
    """Submit a request, wait with bounded timeout, and verify state."""
    fake = _FakeGatewayClient()

    with patch(
        "audiagentic.components.agents.agents_gateway_client.get_gateway_client",
        return_value=fake,
    ):
        from audiagentic.components.agents.agents_gateway_client import (
            get_gateway_client,
        )

        client = get_gateway_client()
        submit_result = client.submit_llm_request(
            Path("/fake/root"),
            prompt_body="test prompt",
            metadata={"subject": "req_bounded"},
        )

        assert submit_result["state"] == "queued"
        assert submit_result["request-id"] == "req_bounded"

        status = client.wait_llm_request(
            Path("/fake/root"),
            "req_bounded",
            timeout_seconds=1,
        )

        assert status["request-id"] == "req_bounded"
        # The in-memory record still has prompt-body; redaction happens at
        # persistence time (write_record in agents_gateway_store).
        assert "prompt-body" in status


def test_fake_client_cancel_sets_state() -> None:
    """Cancel a request and verify the state transition."""
    fake = _FakeGatewayClient()

    with patch(
        "audiagentic.components.agents.agents_gateway_client.get_gateway_client",
        return_value=fake,
    ):
        from audiagentic.components.agents.agents_gateway_client import (
            get_gateway_client,
        )

        client = get_gateway_client()
        client.submit_llm_request(
            Path("/fake/root"),
            prompt_body="test",
            metadata={"subject": "req_cancel"},
        )

        cancel_result = client.cancel_llm_request(Path("/fake/root"), "req_cancel")
        assert cancel_result["state"] == "cancelled"

        status = client.get_llm_request(Path("/fake/root"), "req_cancel")
        assert status["state"] == "cancelled"


def test_run_redacts_via_helper() -> None:
    """run_gateway_request.py's _redact_result strips sensitive data from run output."""
    mod = _load_redact_helper()
    redact = getattr(mod, "_redact_result")

    fake = _FakeGatewayClient()
    raw = fake.run_llm_request(Path("/fake/root"), prompt_body="secret", source="test")

    redacted = redact(raw)

    assert "prompt-body" not in redacted
    assert "output" not in redacted or redacted.get("output") is None
    completion = redacted.get("completion", {})
    assert "stdout" not in completion
