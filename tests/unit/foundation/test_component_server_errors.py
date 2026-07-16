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
    # stdout is BULK_KEY — content-redacted, NOT blanked. "secret output" has no
    # secret pattern so passes through intact (the regression this revision fixes).
    assert result["details"]["stdout"] == "secret output"
    # stderr is BULK_KEY — content-redacted. The token value is replaced but key preserved.
    assert result["details"]["stderr"] == "token: [REDACTED]"
    assert result["details"]["safe"] == "ok"
    # api_key is SECRET_KEY — blanket-replaced.
    assert result["details"]["nested"]["api_key"] == "[REDACTED]"


def test_report_error_redacts_secret_patterns_in_generic_error() -> None:
    result = report_error(
        "test",
        "run",
        RuntimeError("failed with token: abc123"),
        logging.getLogger(__name__),
    )

    assert result == {
        "ok": False,
        "error": "failed with token: [REDACTED]",
        "tool": "run",
    }
