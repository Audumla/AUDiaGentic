"""AS36 integration tests — terminal-quality wiring into gateway status/wait
and the latest_turn_quality_summary helper.

Verifies that the pure classifier from agents_terminal_quality is called from
the right places in the gateway API and that only bounded scalar evidence flows
through to public projections (no raw prompt/tool data)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

from audiagentic.components.agents import agents_gateway_api as gateway
from audiagentic.components.agents import agents_gateway_sessions_store as session_store
from audiagentic.components.agents.agents_api import create_profile
from audiagentic.components.agents.agents_terminal_quality import (
    CLASSIFIER_VERSION,
    TerminalQualityLabel,
)
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state

# Forbidden keys that must never appear in terminal-quality evidence.
_FORBIDDEN_EVIDENCE_KEYS = {
    "prompt-body",
    "prompt_body",
    "output",
    "tool_args",
    "tool-args",
    "tool-calls",
    "tool_calls",
    "tool-results",
    "tool_results",
    "provider-session-ref",
    "binding-ref",
}


def _make_profile(project_root: Path, profile_id: str, provider_id: str, **params) -> None:
    create_profile(project_root, {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "model_id": "gpt-4o",
        "is_default": True,
        "params": params,
    })
    set_implementation_state(project_root, "providers", provider_id, ImplementationState(enabled=True))


def _result(data: dict) -> SimpleNamespace:
    return SimpleNamespace(result_data=data)


# ===========================================================================
# latest_turn_quality_summary — bounded scalar helper (AS36 step 4)
# ===========================================================================

class TestLatestTurnQualitySummary:
    """Verify the quality-summary helper returns only bounded scalar fields."""

    def _write_timeline(self, project_root: Path, session_id: str, entries: list[dict]) -> None:
        import json as _json

        from audiagentic.components.agents.agents_paths import gateway_session_timeline_path

        path = gateway_session_timeline_path(project_root, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            for entry in entries:
                f.write(_json.dumps(entry) + "\n")

    def test_returns_bounded_scalars_only(self, tmp_path: Path):
        session_id = "ses_test01"
        self._write_timeline(tmp_path, session_id, [
            {
                "event": "session.turn.assistant-message",
                "state": "active",
                "timestamp": "2026-07-01T00:00:00Z",
                "attributes": {
                    "request-id": "req_x",
                    "kind": "assistant-message",
                    "sequence": 5,
                },
            },
            {
                "event": "session.turn.tool-call",
                "state": "active",
                "timestamp": "2026-07-01T00:01:00Z",
                "attributes": {
                    "request-id": "req_x",
                    "kind": "tool-call",
                    "sequence": 10,
                },
            },
            {
                "event": "session.turn.assistant-message",
                "state": "active",
                "timestamp": "2026-07-01T00:02:00Z",
                "attributes": {
                    "request-id": "req_x",
                    "kind": "assistant-message",
                    "sequence": 15,
                    "stop-reason": "end_turn",
                },
            },
        ])

        summary = session_store.latest_turn_quality_summary(
            tmp_path, session_id, "req_x"
        )

        assert summary is not None
        assert summary["event-count"] == 3
        assert summary["last-event-kind"] == "assistant-message"
        assert summary["last-event-sequence"] == 15
        assert summary["last-assistant-event-sequence"] == 15
        assert summary["last-tool-event-sequence"] == 10
        assert summary["stop-reason"] == "end_turn"

        # All values are scalar/bounded (no text, no tool args)
        for key, val in summary.items():
            if val is not None:
                assert isinstance(val, (str, int, float, bool)), (
                    f"Non-scalar value in quality summary field '{key}': {type(val)}"
                )

    def test_filters_by_request_id(self, tmp_path: Path):
        session_id = "ses_test02"
        self._write_timeline(tmp_path, session_id, [
            {
                "event": "session.turn.tool-call",
                "state": "active",
                "timestamp": "2026-07-01T00:00:00Z",
                "attributes": {
                    "request-id": "req_other",
                    "kind": "tool-call",
                    "sequence": 1,
                },
            },
            {
                "event": "session.turn.assistant-message",
                "state": "active",
                "timestamp": "2026-07-01T00:01:00Z",
                "attributes": {
                    "request-id": "req_target",
                    "kind": "assistant-message",
                    "sequence": 5,
                },
            },
        ])

        summary = session_store.latest_turn_quality_summary(
            tmp_path, session_id, "req_target"
        )
        assert summary is not None
        assert summary["event-count"] == 1  # only req_target events
        assert summary["last-event-kind"] == "assistant-message"

    def test_returns_none_when_no_timeline(self, tmp_path: Path):
        session_id = "ses_missing"
        summary = session_store.latest_turn_quality_summary(
            tmp_path, session_id, "req_x"
        )
        assert summary is None

    def test_no_text_content_in_summary(self, tmp_path: Path):
        """Tool-call text and args must not leak into quality summary."""
        session_id = "ses_test03"
        self._write_timeline(tmp_path, session_id, [
            {
                "event": "session.turn.tool-call",
                "state": "active",
                "timestamp": "2026-07-01T00:00:00Z",
                "attributes": {
                    "request-id": "req_x",
                    "kind": "tool-call",
                    "sequence": 3,
                    # These fields might exist in raw timeline but must not
                    # appear in quality summary:
                    "tool-name": "read_file",
                    "tool-args": {"path": "/secret/file.py"},
                    "output-text": "def secret(): pass",
                },
            },
        ])

        summary = session_store.latest_turn_quality_summary(
            tmp_path, session_id, "req_x"
        )
        assert summary is not None
        # Only bounded scalar fields allowed
        for key in summary:
            assert key in {
                "event-count", "last-event-kind", "last-event-sequence",
                "last-event-at", "last-assistant-event-sequence",
                "last-tool-event-sequence", "result-sequence", "stop-reason",
            }, f"Unexpected key '{key}' in quality summary"

        # No raw text should leak
        summary_str = json.dumps(summary)
        assert "secret" not in summary_str.lower()
        assert "read_file" not in summary_str
        assert "tool-name" not in summary_str
        assert "tool-args" not in summary_str


# ===========================================================================
# Terminal-quality in request_runtime_status (AS36 step 5a)
# ===========================================================================

class TestTerminalQualityInStatus:
    """Verify terminal-quality appears for terminal requests in runtime status."""

    def test_terminal_quality_present_for_completed_request(self, tmp_path: Path, monkeypatch):
        _make_profile(tmp_path, "default", "local-openai")

        def fake_execute_provider(*, identity, execution_request, timeout_seconds):
            return _result({
                "provider-id": execution_request["provider-id"],
                "status": "ok",
                "model": "gpt-4o",
                "output": "All tests passed. Summary of changes applied.",
            })

        monkeypatch.setattr(
            "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
            fake_execute_provider,
        )

        result = gateway.run_execution_request(tmp_path, prompt_body="hi")
        assert result["state"] == "completed"

        status = gateway.request_runtime_status(tmp_path, result["request-id"])

        assert "terminal-quality" in status, (
            "terminal-quality should be present for completed requests"
        )
        tq = status["terminal-quality"]
        assert tq["label"] == TerminalQualityLabel.CLEAN.value
        assert tq["classifier_version"] == CLASSIFIER_VERSION
        assert "signals" in tq

    def test_terminal_quality_absent_for_running_request(self, tmp_path: Path, monkeypatch):
        _make_profile(tmp_path, "default", "local-openai")
        hold = threading.Event()

        def slow_execute_provider(*, identity, execution_request, timeout_seconds):
            hold.wait(timeout=5)
            return _result({
                "provider-id": execution_request["provider-id"],
                "status": "ok",
                "model": "gpt-4o",
                "output": "done",
            })

        monkeypatch.setattr(
            "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
            slow_execute_provider,
        )

        submitted = gateway.submit_execution_request(tmp_path, prompt_body="hi")
        status = gateway.request_runtime_status(tmp_path, submitted["request-id"])

        assert "terminal-quality" not in status, (
            "terminal-quality should NOT be present for running requests"
        )

        hold.set()
        gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=5)

    def test_terminal_quality_sh07_shape(self, tmp_path: Path, monkeypatch):
        """SH07 incident shape: completed but output ends mid-progress."""
        _make_profile(tmp_path, "default", "local-openai")

        def fake_execute_provider(*, identity, execution_request, timeout_seconds):
            return _result({
                "provider-id": execution_request["provider-id"],
                "status": "ok",
                "model": "gpt-4o",
                "output": (
                    "I have updated the configuration files and verified the changes.\n"
                    "The tests are passing for the core module.\n"
                    "Now update the remaining modules:"
                ),
            })

        monkeypatch.setattr(
            "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
            fake_execute_provider,
        )

        result = gateway.run_execution_request(tmp_path, prompt_body="hi")
        assert result["state"] == "completed"

        status = gateway.request_runtime_status(tmp_path, result["request-id"])
        tq = status["terminal-quality"]

        assert tq["label"] in (
            TerminalQualityLabel.PREMATURE_HALT_SUSPECTED.value,
            TerminalQualityLabel.SUSPICIOUS.value,
        ), f"SH07 shape should be suspicious/premature-halt, got {tq['label']}"

    def test_terminal_quality_evidence_no_raw_content(self, tmp_path: Path, monkeypatch):
        """Signal evidence must not contain raw prompt/output/tool data."""
        _make_profile(tmp_path, "default", "local-openai")

        def fake_execute_provider(*, identity, execution_request, timeout_seconds):
            return _result({
                "provider-id": execution_request["provider-id"],
                "status": "ok",
                "model": "gpt-4o",
                "output": (
                    "First, let me read the file.\n"
                    "Now I'll update it.\n"
                    "Next, run tests."
                ),
            })

        monkeypatch.setattr(
            "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
            fake_execute_provider,
        )

        result = gateway.run_execution_request(tmp_path, prompt_body="SECRET PROMPT")
        assert result["state"] == "completed"

        status = gateway.request_runtime_status(tmp_path, result["request-id"])
        tq = status["terminal-quality"]

        # Check no forbidden keys in signal evidence
        for sig in tq.get("signals", []):
            ev = sig.get("evidence", {})
            for key in _FORBIDDEN_EVIDENCE_KEYS:
                assert key not in ev, (
                    f"Forbidden key '{key}' in terminal-quality signal evidence"
                )
            # No raw prompt text in evidence values
            ev_str = json.dumps(ev)
            assert "SECRET PROMPT" not in ev_str

    def test_terminal_quality_for_failed_request(self, tmp_path: Path, monkeypatch):
        """Failed requests are also terminal and should carry terminal-quality."""
        _make_profile(tmp_path, "default", "local-openai")

        def failing_execute_provider(**_kwargs):
            from audiagentic.foundation.contracts.errors import AudiaGenticError
            raise AudiaGenticError(code="VAL-FAKE-001", kind="providers", message="broke")

        monkeypatch.setattr(
            "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
            failing_execute_provider,
        )

        result = gateway.run_execution_request(tmp_path, prompt_body="hi")
        assert result["state"] == "failed"

        status = gateway.request_runtime_status(tmp_path, result["request-id"])
        assert "terminal-quality" in status


# ===========================================================================
# Terminal-quality in wait_execution_request (AS36 step 5b)
# ===========================================================================

class TestTerminalQualityInWait:
    """Verify terminal-quality appears when wait returns a terminal record."""

    def test_terminal_quality_in_wait_terminal(self, tmp_path: Path, monkeypatch):
        _make_profile(tmp_path, "default", "local-openai")

        def fake_execute_provider(*, identity, execution_request, timeout_seconds):
            return _result({
                "provider-id": execution_request["provider-id"],
                "status": "ok",
                "model": "gpt-4o",
                "output": "Done.",
            })

        monkeypatch.setattr(
            "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
            fake_execute_provider,
        )

        submitted = gateway.submit_execution_request(tmp_path, prompt_body="hi")
        result = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=10)

        assert result["state"] == "completed"
        assert "terminal-quality" in result, (
            "wait_execution_request should include terminal-quality for terminal results"
        )
        assert result["terminal-quality"]["label"] == TerminalQualityLabel.CLEAN.value

    def test_no_terminal_quality_in_wait_timeout(self, tmp_path: Path, monkeypatch):
        """Non-terminal timeout response must NOT carry terminal-quality."""
        _make_profile(tmp_path, "default", "local-openai")
        hold = threading.Event()

        def slow_execute_provider(*, identity, execution_request, timeout_seconds):
            hold.wait(timeout=5)
            return _result({
                "provider-id": execution_request["provider-id"],
                "status": "ok",
                "model": "gpt-4o",
                "output": "done",
            })

        monkeypatch.setattr(
            "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
            slow_execute_provider,
        )

        submitted = gateway.submit_execution_request(tmp_path, prompt_body="hi")
        result = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=0.2)

        assert result.get("wait-timeout") is True
        assert "terminal-quality" not in result, (
            "terminal-quality should NOT appear for non-terminal wait timeouts"
        )

        hold.set()
        gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=5)

    def test_terminal_quality_in_wait_sh07_shape(self, tmp_path: Path, monkeypatch):
        """SH07 shape: completed but output ends mid-progress — should be suspicious."""
        _make_profile(tmp_path, "default", "local-openai")

        def fake_execute_provider(*, identity, execution_request, timeout_seconds):
            return _result({
                "provider-id": execution_request["provider-id"],
                "status": "ok",
                "model": "gpt-4o",
                "output": (
                    "I have updated the configuration files and verified the changes.\n"
                    "The tests are passing for the core module.\n"
                    "Now update the remaining modules:"
                ),
            })

        monkeypatch.setattr(
            "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
            fake_execute_provider,
        )

        submitted = gateway.submit_execution_request(tmp_path, prompt_body="hi")
        result = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=10)

        assert result["state"] == "completed"
        assert "terminal-quality" in result
        tq = result["terminal-quality"]
        assert tq["label"] in (
            TerminalQualityLabel.PREMATURE_HALT_SUSPECTED.value,
            TerminalQualityLabel.SUSPICIOUS.value,
        ), f"SH07 shape should be suspicious/premature-halt, got {tq['label']}"

    def test_terminal_quality_in_wait_with_session(self, tmp_path: Path, monkeypatch):
        """Terminal quality should work with session_id present (quality summary available)."""
        _make_profile(tmp_path, "default", "local-openai")

        def fake_execute_provider(*, identity, execution_request, timeout_seconds):
            return _result({
                "provider-id": execution_request["provider-id"],
                "status": "ok",
                "model": "gpt-4o",
                "output": "All tests passed. Summary of changes: config updated.",
            })

        monkeypatch.setattr(
            "audiagentic.components.agents.agents_gateway_worker.execute_isolated_provider_turn",
            fake_execute_provider,
        )

        submitted = gateway.submit_execution_request(tmp_path, prompt_body="hi")
        result = gateway.wait_execution_request(tmp_path, submitted["request-id"], timeout_seconds=10)

        assert result["state"] == "completed"
        assert "terminal-quality" in result
        # The classifier should have been called regardless of session timeline
        tq = result["terminal-quality"]
        assert tq["classifier_version"] == CLASSIFIER_VERSION
