from __future__ import annotations

import logging

import pytest

from audiagentic.foundation.contracts.errors import (
    AudiaGenticError,
    register_error_resolution,
)
from audiagentic.foundation.mcp.component_server import (
    ToolError,
    _tool_error_text,
    tool_boundary,
)


def test_tool_error_text_redacts_secret_patterns_in_generic_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR):
        text = _tool_error_text(
            RuntimeError("failed with token: abc123"),
            "run",
            logging.getLogger(__name__),
        )

    assert text == "failed with token: [REDACTED]"


def test_tool_error_text_redacts_secret_shaped_content_in_raw_exception() -> None:
    # Verifies the leak this item closes: previously an uncaught exception's
    # str() reached the client verbatim through the 13 servers with no
    # report_error() call at all.
    text = _tool_error_text(
        RuntimeError("login failed: sk-liveabcdefghijklmnopqrstuvwx"),
        "run",
        logging.getLogger(__name__),
    )

    assert "sk-liveabcdefghijklmnopqrstuvwx" not in text
    assert "[REDACTED]" in text


def test_tool_error_text_redacts_audiagentic_error_message() -> None:
    # _Error.__str__ never redacts `message` — this is the gap CC62 closes:
    # a domain error's own message text must not leak secret-shaped content.
    register_error_resolution("EXT-TEST-010", "")
    error = AudiaGenticError(
        code="EXT-TEST-010",
        kind="test-errors",
        message="login failed: sk-liveabcdefghijklmnopqrstuvwx",
    )

    text = _tool_error_text(error, "run", logging.getLogger(__name__))

    assert "sk-liveabcdefghijklmnopqrstuvwx" not in text
    assert text.startswith("EXT-TEST-010: ")
    assert "[REDACTED]" in text


def test_tool_error_text_includes_code_and_message() -> None:
    register_error_resolution("EXT-TEST-011", "")
    error = AudiaGenticError(
        code="EXT-TEST-011",
        kind="test-errors",
        message="tool failed",
    )

    text = _tool_error_text(error, "run", logging.getLogger(__name__))

    assert text == "EXT-TEST-011: tool failed"


def test_tool_error_text_includes_resolution_when_registered() -> None:
    register_error_resolution("EXT-TEST-012", "check the widget configuration")
    error = AudiaGenticError(
        code="EXT-TEST-012",
        kind="test-errors",
        message="tool failed",
    )

    text = _tool_error_text(error, "run", logging.getLogger(__name__))

    assert "resolution: check the widget configuration" in text


def test_tool_error_text_includes_redacted_details_when_present() -> None:
    register_error_resolution("EXT-TEST-013", "")
    error = AudiaGenticError(
        code="EXT-TEST-013",
        kind="test-errors",
        message="tool failed",
        details={"stdout": "secret output", "nested": {"api_key": "abc123"}},
    )

    text = _tool_error_text(error, "run", logging.getLogger(__name__))

    assert "details:" in text
    assert '"api_key": "[REDACTED]"' in text


def test_tool_error_text_logs_full_structured_envelope_for_operators(
    caplog: pytest.LogCaptureFixture,
) -> None:
    register_error_resolution("EXT-TEST-014", "")
    error = AudiaGenticError(
        code="EXT-TEST-014",
        kind="test-errors",
        message="tool failed",
        details={"nested": {"api_key": "abc123"}},
    )

    with caplog.at_level(logging.ERROR):
        _tool_error_text(error, "run", logging.getLogger(__name__))

    record = next(r for r in caplog.records if r.message == "tool failed")
    envelope = record.__dict__["error"]
    assert envelope["error-code"] == "EXT-TEST-014"
    assert envelope["contract-version"] == "v1"
    assert envelope["details"]["nested"]["api_key"] == "[REDACTED]"


def test_tool_error_text_fail_closed_collapses_when_secret_survives() -> None:
    # resolution text is developer-authored and not passed through redact_text,
    # so it is the one path where secret-shaped content could still reach the
    # final text — the fail-closed check exists to catch exactly this.
    register_error_resolution(
        "EXT-TEST-015", "rotate the key sk-liveabcdefghijklmnopqrstuvwx"
    )
    error = AudiaGenticError(
        code="EXT-TEST-015",
        kind="test-errors",
        message="tool failed",
    )

    text = _tool_error_text(error, "run", logging.getLogger(__name__))

    assert text == "tool failed"


def test_tool_boundary_sync_raises_tool_error_with_redacted_text() -> None:
    @tool_boundary
    def _tool() -> dict[str, str]:
        raise RuntimeError("failed with token: abc123")

    with pytest.raises(ToolError) as excinfo:
        _tool()

    assert "abc123" not in str(excinfo.value)
    assert "[REDACTED]" in str(excinfo.value)


def test_tool_boundary_sync_returns_result_on_success() -> None:
    @tool_boundary
    def _tool() -> dict[str, str]:
        return {"ok": "yes"}

    assert _tool() == {"ok": "yes"}


@pytest.mark.asyncio
async def test_tool_boundary_async_raises_tool_error_with_redacted_text() -> None:
    @tool_boundary
    async def _tool() -> dict[str, str]:
        raise RuntimeError("failed with token: abc123")

    with pytest.raises(ToolError) as excinfo:
        await _tool()

    assert "abc123" not in str(excinfo.value)
    assert "[REDACTED]" in str(excinfo.value)


@pytest.mark.asyncio
async def test_tool_boundary_async_returns_result_on_success() -> None:
    @tool_boundary
    async def _tool() -> dict[str, str]:
        return {"ok": "yes"}

    assert await _tool() == {"ok": "yes"}


def test_tool_boundary_raises_tool_error_for_audiagentic_error() -> None:
    @tool_boundary
    def _tool() -> dict[str, str]:
        raise AudiaGenticError(
            code="VAL-PROJFILE-001", kind="test-errors", message="bad input"
        )

    with pytest.raises(ToolError) as excinfo:
        _tool()

    assert "VAL-PROJFILE-001" in str(excinfo.value)
