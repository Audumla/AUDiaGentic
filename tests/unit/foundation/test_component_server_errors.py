from __future__ import annotations

import logging

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.mcp.component_server import report_error


def test_report_error_redacts_structured_error_details() -> None:
    error = AudiaGenticError(
        code="EXT-TEST-001",
        kind="test-errors",
        message="tool failed",
        details={
            "stdout": "secret output",
            "stderr": "token: abc123",
            "safe": "ok",
            "nested": {"api_key": "abc123"},
        },
    )

    result = report_error("test", "run", error, logging.getLogger(__name__))

    assert result["ok"] is False
    assert result["error-code"] == "EXT-TEST-001"
    assert result["message"] == "tool failed"
    assert result["tool"] == "run"
    assert result["details"]["stdout"] == "[redacted]"
    assert result["details"]["stderr"] == "[redacted]"
    assert result["details"]["safe"] == "ok"
    assert result["details"]["nested"]["api_key"] == "[redacted]"


def test_report_error_redacts_secret_patterns_in_generic_error() -> None:
    result = report_error(
        "test",
        "run",
        RuntimeError("failed with token: abc123"),
        logging.getLogger(__name__),
    )

    assert result == {
        "ok": False,
        "error": "failed with token: [redacted]",
        "tool": "run",
    }
