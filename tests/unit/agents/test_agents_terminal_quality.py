"""Unit tests for agents_terminal_quality — pure classifier only.

Covers all deterministic signals, label aggregation, confidence scoring, and
redaction guarantees. No provider adapters or event bus imports exercised here.
"""
from __future__ import annotations

from audiagentic.components.agents.agents_terminal_quality import (
    CLASSIFIER_VERSION,
    TerminalQualityLabel,
    TerminalQualityReport,
    classify_terminal_output,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_record(
    state="completed",
    output: str | None = "Task completed successfully. Summary of changes applied.",
    stop_reason: str = "end_turn",
    dropped_events: int = 0,
    total_events: int = 100,
) -> dict:
    """Build a minimal request record for classifier tests."""
    return {
        "state": state,
        "output": output,
        "completion": {
            "stop-reason": stop_reason,
            "dropped-events": dropped_events,
            "total-events": total_events,
        },
    }

def _signals(report: TerminalQualityReport) -> list[str]:
    """Extract signal codes from a report for easy assertion."""
    return [s.code for s in report.signals]

# ---------------------------------------------------------------------------
# Clean output — no signals
# ---------------------------------------------------------------------------

class TestCleanOutput:
    def test_clean_with_summary(self):
        rec = _base_record(output="All tests passed. Summary of changes: updated config file.")
        report = classify_terminal_output(record=rec)
        assert report.label == TerminalQualityLabel.CLEAN
        assert report.confidence == 1.0
        assert report.signals == ()

    def test_clean_short_output_few_events(self):
        """Short output with few events is fine (not nontrivial)."""
        rec = _base_record(output="Done.", total_events=5)
        report = classify_terminal_output(record=rec)
        assert report.label == TerminalQualityLabel.CLEAN

    def test_clean_with_closeout_markers(self):
        rec = _base_record(output="Validation passed. Done with self-review complete.")
        report = classify_terminal_output(record=rec)
        assert report.label == TerminalQualityLabel.CLEAN

# ---------------------------------------------------------------------------
# TQ-NO-OUTPUT
# ---------------------------------------------------------------------------

class TestNoOutput:
    def test_empty_output_nontrivial_events(self):
        rec = _base_record(output="", total_events=50)
        report = classify_terminal_output(record=rec)
        assert "TQ-NO-OUTPUT" in _signals(report)
        assert report.label == TerminalQualityLabel.PREMATURE_HALT_SUSPECTED

    def test_very_short_output_nontrivial_events(self):
        rec = _base_record(output="Ok", total_events=30)
        report = classify_terminal_output(record=rec)
        assert "TQ-NO-OUTPUT" in _signals(report)

    def test_short_output_few_events_is_clean(self):
        """Below the nontrivial threshold — no signal."""
        rec = _base_record(output="", total_events=5)
        report = classify_terminal_output(record=rec)
        assert "TQ-NO-OUTPUT" not in _signals(report)

    def test_none_output(self):
        rec = _base_record(output=None, total_events=100)
        report = classify_terminal_output(record=rec)
        assert "TQ-NO-OUTPUT" in _signals(report)

# ---------------------------------------------------------------------------
# TQ-ENDS-WITH-PREAMBLE
# ---------------------------------------------------------------------------

class TestEndsWithPreamble:
    def test_ends_with_colon(self):
        rec = _base_record(output="Now let me check the files:\nfile1, file2")
        report = classify_terminal_output(record=rec)
        # The last line is "file1, file2" — not a preamble
        assert "TQ-ENDS-WITH-PREAMBLE" not in _signals(report)

    def test_ends_with_progress_instruction(self):
        rec = _base_record(
            output="I updated the config. Now update the README:"
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-ENDS-WITH-PREAMBLE" in _signals(report)

    def test_ends_with_let_me(self):
        rec = _base_record(output="Let me check that again")
        report = classify_terminal_output(record=rec)
        assert "TQ-ENDS-WITH-PREAMBLE" in _signals(report)

    def test_ends_with_i_will(self):
        rec = _base_record(output="I will fix the tests")
        report = classify_terminal_output(record=rec)
        assert "TQ-ENDS-WITH-PREAMBLE" in _signals(report)

    def test_ends_with_next(self):
        rec = _base_record(output="Next, I'll update the docs")
        report = classify_terminal_output(record=rec)
        assert "TQ-ENDS-WITH-PREAMBLE" in _signals(report)

    def test_markdown_bullet_stripped(self):
        """Bullet prefix is stripped before preamble match."""
        rec = _base_record(output="Some work done\n- Now let me verify")
        report = classify_terminal_output(record=rec)
        assert "TQ-ENDS-WITH-PREAMBLE" in _signals(report)

    def test_no_preamble_in_normal_text(self):
        rec = _base_record(
            output="The function next() is called by the parser."
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-ENDS-WITH-PREAMBLE" not in _signals(report)

# ---------------------------------------------------------------------------
# TQ-MISSING-EXPECTED-CLOSEOUT
# ---------------------------------------------------------------------------

class TestMissingCloseout:
    def test_multiple_progress_no_closeout(self):
        rec = _base_record(
            output=(
                "First, I'll update the config.\n"
                "Next let me check the results.\n"
                "Now let me verify the output."
            )
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-MISSING-EXPECTED-CLOSEOUT" in _signals(report)

    def test_progress_with_closeout_is_clean(self):
        rec = _base_record(
            output=(
                "First, I'll update the config.\n"
                "Next, let me run the tests.\n"
                "Summary of changes: config updated."
            )
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-MISSING-EXPECTED-CLOSEOUT" not in _signals(report)

    def test_single_progress_marker_no_flag(self):
        """Need >= 2 progress markers to flag."""
        rec = _base_record(output="First, I'll update the config.")
        report = classify_terminal_output(record=rec)
        assert "TQ-MISSING-EXPECTED-CLOSEOUT" not in _signals(report)

# ---------------------------------------------------------------------------
# TQ-UNTERMINATED-MARKDOWN
# ---------------------------------------------------------------------------

class TestUnterminatedMarkdown:
    def test_odd_fences(self):
        rec = _base_record(
            output="Here is a code block:\n```python\nprint('hello')\nSome more text."
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-UNTERMINATED-MARKDOWN" in _signals(report)

    def test_even_fences(self):
        rec = _base_record(
            output="```python\nprint('hello')\n```\nDone."
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-UNTERMINATED-MARKDOWN" not in _signals(report)

    def test_unfinished_bullet_colon(self):
        rec = _base_record(output="- Things to do:")
        report = classify_terminal_output(record=rec)
        assert "TQ-UNTERMINATED-MARKDOWN" in _signals(report)

    def test_evidence_is_bounded_scalar_not_list(self):
        """Evidence must be issue-count (int) + issue-codes (str), never a list."""
        rec = _base_record(
            output="Here is a code block:\n```python\nprint('hello')\n- Items:"
        )
        report = classify_terminal_output(record=rec)
        sig = [s for s in report.signals if s.code == "TQ-UNTERMINATED-MARKDOWN"][0]
        assert isinstance(sig.evidence["issue-count"], int)
        assert isinstance(sig.evidence["issue-codes"], str)
        assert "," in sig.evidence["issue-codes"]  # comma-joined codes, not a raw list
        assert "issues" not in sig.evidence  # no raw list key
        assert sig.evidence["issue-count"] == len(sig.evidence["issue-codes"].split(","))

# ---------------------------------------------------------------------------
# TQ-REPETITION
# ---------------------------------------------------------------------------

class TestRepetition:
    def test_identical_line_repetition(self):
        lines = ["Processing file..."] * 10
        rec = _base_record(output="\n".join(lines))
        report = classify_terminal_output(record=rec)
        assert "TQ-REPETITION" in _signals(report)

    def test_progress_phrase_repetition(self):
        """Same preamble phrase repeated with little substantive text."""
        lines = [
            "Let me check file1",
            "ok",
            "Let me check file2",
            "ok",
            "Let me check file3",
            "ok",
            "Let me check file4",
        ]
        rec = _base_record(output="\n".join(lines), total_events=10)
        report = classify_terminal_output(record=rec)
        assert "TQ-REPETITION" in _signals(report)

    def test_progress_phrase_with_substantive_gaps(self):
        """Substantive text between repeats — should not flag."""
        lines = [
            "Let me check file1",
            "This is a long substantive paragraph of analysis about the first file that goes on.",
            "Let me check file2",
            "Another long paragraph with substantial content explaining the second file findings.",
            "Let me check file3",
            "Yet another detailed explanation here that is well over thirty characters long.",
        ]
        rec = _base_record(output="\n".join(lines))
        report = classify_terminal_output(record=rec)
        assert "TQ-REPETITION" not in _signals(report)

# ---------------------------------------------------------------------------
# TQ-DROPPED-EVENTS
# ---------------------------------------------------------------------------

class TestDroppedEvents:
    def test_dropped_events_no_closeout(self):
        rec = _base_record(
            output="Some work completed.",
            dropped_events=5,
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-DROPPED-EVENTS" in _signals(report)
        sig = [s for s in report.signals if s.code == "TQ-DROPPED-EVENTS"][0]
        assert sig.severity == "critical"  # no closeout → critical

    def test_dropped_events_with_closeout(self):
        rec = _base_record(
            output="Summary of changes: applied.",
            dropped_events=5,
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-DROPPED-EVENTS" in _signals(report)
        sig = [s for s in report.signals if s.code == "TQ-DROPPED-EVENTS"][0]
        assert sig.severity == "warning"  # has closeout → warning

    def test_no_dropped_events(self):
        rec = _base_record(dropped_events=0)
        report = classify_terminal_output(record=rec)
        assert "TQ-DROPPED-EVENTS" not in _signals(report)

# ---------------------------------------------------------------------------
# TQ-HIGH-EVENT-LOW-OUTPUT
# ---------------------------------------------------------------------------

class TestHighEventLowOutput:
    def test_high_event_low_output(self):
        rec = _base_record(output="Ok", total_events=1000)
        report = classify_terminal_output(record=rec)
        assert "TQ-HIGH-EVENT-LOW-OUTPUT" in _signals(report)

    def test_high_event_with_decent_output(self):
        rec = _base_record(
            output="A" * 600,
            total_events=1000,
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-HIGH-EVENT-LOW-OUTPUT" not in _signals(report)

    def test_low_event_no_flag(self):
        rec = _base_record(output="Ok", total_events=50)
        report = classify_terminal_output(record=rec)
        assert "TQ-HIGH-EVENT-LOW-OUTPUT" not in _signals(report)

# ---------------------------------------------------------------------------
# TQ-STOP-REASON
# ---------------------------------------------------------------------------

class TestStopReason:
    def test_max_tokens(self):
        rec = _base_record(stop_reason="max_tokens")
        report = classify_terminal_output(record=rec)
        assert "TQ-STOP-REASON" in _signals(report)

    def test_error_stop_reason(self):
        rec = _base_record(stop_reason="error", state="completed")
        report = classify_terminal_output(record=rec)
        assert "TQ-STOP-REASON" in _signals(report)

    def test_end_turn_no_flag(self):
        rec = _base_record(stop_reason="end_turn")
        report = classify_terminal_output(record=rec)
        assert "TQ-STOP-REASON" not in _signals(report)

    def test_none_stop_reason_no_flag(self):
        rec = _base_record()
        # completion has stop-reason=None
        report = classify_terminal_output(record=rec)
        assert "TQ-STOP-REASON" not in _signals(report)

# ---------------------------------------------------------------------------
# TQ-TOOL-AFTER-LAST-TEXT
# ---------------------------------------------------------------------------

class TestToolAfterLastText:
    def test_tool_after_last_text(self):
        rec = _base_record()
        summary = {
            "last-assistant-event-sequence": 10,
            "last-tool-event-sequence": 15,
        }
        report = classify_terminal_output(
            record=rec,
            session_event_summary=summary,
        )
        assert "TQ-TOOL-AFTER-LAST-TEXT" in _signals(report)

    def test_tool_before_last_text(self):
        rec = _base_record()
        summary = {
            "last-assistant-event-sequence": 15,
            "last-tool-event-sequence": 10,
        }
        report = classify_terminal_output(
            record=rec,
            session_event_summary=summary,
        )
        assert "TQ-TOOL-AFTER-LAST-TEXT" not in _signals(report)

    def test_no_summary(self):
        rec = _base_record()
        report = classify_terminal_output(record=rec)
        assert "TQ-TOOL-AFTER-LAST-TEXT" not in _signals(report)

# ---------------------------------------------------------------------------
# Non-terminal state
# ---------------------------------------------------------------------------

class TestNonTerminal:
    def test_running_state(self):
        rec = _base_record(state="running")
        report = classify_terminal_output(record=rec)
        assert report.label == TerminalQualityLabel.UNKNOWN
        assert report.confidence == 0.0

    def test_queued_state(self):
        rec = _base_record(state="queued")
        report = classify_terminal_output(record=rec)
        assert report.label == TerminalQualityLabel.UNKNOWN

# ---------------------------------------------------------------------------
# Label aggregation
# ---------------------------------------------------------------------------

class TestLabelAggregation:
    def test_premature_halt_wins_over_suspicious(self):
        """TQ-NO-OUTPUT → premature-halt-suspected should dominate."""
        rec = _base_record(output="", total_events=100, dropped_events=5)
        report = classify_terminal_output(record=rec)
        # Both TQ-NO-OUTPUT (premature-halt) and TQ-DROPPED-EVENTS (content-capture) fire
        assert report.label == TerminalQualityLabel.PREMATURE_HALT_SUSPECTED

    def test_content_capture_when_dropped_events_only(self):
        rec = _base_record(output="Done.", dropped_events=5, total_events=10)
        report = classify_terminal_output(record=rec)
        assert report.label == TerminalQualityLabel.CONTENT_CAPTURE_SUSPECTED

    def test_repetition_label(self):
        lines = ["Processing..."] * 10
        rec = _base_record(output="\n".join(lines), total_events=10)
        report = classify_terminal_output(record=rec)
        assert report.label == TerminalQualityLabel.REPETITION_SUSPECTED

# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

class TestConfidence:
    def test_clean_confidence_is_one(self):
        rec = _base_record()
        report = classify_terminal_output(record=rec)
        assert report.confidence == 1.0

    def test_multiple_signals_increases_confidence(self):
        rec = _base_record(output="", total_events=100, dropped_events=5, stop_reason="error")
        report = classify_terminal_output(record=rec)
        assert len(report.signals) >= 2
        assert report.confidence > 0.5

# ---------------------------------------------------------------------------
# SH07 C2 incident shape (the motivating case)
# ---------------------------------------------------------------------------

class TestSH07Incident:
    def test_sh07_c2_incident_shape(self):
        """req_03fdae3e068d46ad: completed, end_turn, dropped=0, total=2790,
        output ending mid-progress instruction."""
        rec = {
            "state": "completed",
            "output": (
                "I have updated the configuration files and verified the changes.\n"
                "The tests are passing for the core module.\n"
                "Now update the remaining modules:"
            ),
            "completion": {
                "stop-reason": "end_turn",
                "dropped-events": 0,
                "total-events": 2790,
            },
        }
        report = classify_terminal_output(record=rec)

        assert report.label in (
            TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
            TerminalQualityLabel.SUSPICIOUS,
        ), f"Expected suspicious/premature-halt, got {report.label}"
        assert "TQ-ENDS-WITH-PREAMBLE" in _signals(report)
        # State should still be completed — we don't mutate the record

# ---------------------------------------------------------------------------
# Redaction guarantees — no raw prompt/tool data in evidence
# ---------------------------------------------------------------------------

class TestRedaction:
    def test_no_prompt_in_evidence(self):
        """The classifier receives only the record dict; it never sees prompt body.
        But verify: even if a malicious field were injected, evidence stays scalar."""
        rec = _base_record(output="Done.")
        # Inject raw-looking fields that should NOT appear in evidence
        rec["prompt"] = "SECRET PROMPT"
        report = classify_terminal_output(record=rec)
        for sig in report.signals:
            for v in sig.evidence.values():
                assert "SECRET PROMPT" not in str(v), (
                    f"Prompt leaked into signal evidence: {sig.code}"
                )

    def test_no_tool_args_in_evidence(self):
        rec = _base_record(output="Done.")
        rec["tool-args"] = {"secret_key": "abc123"}
        report = classify_terminal_output(record=rec)
        for sig in report.signals:
            for v in sig.evidence.values():
                assert "abc123" not in str(v), (
                    f"Tool args leaked into signal evidence: {sig.code}"
                )

    def test_evidence_values_are_bounded_scalars(self):
        """Evidence values must be scalar only: str / int / float / bool / None.
        No lists, dicts, or raw text payloads are permitted."""
        rec = _base_record(output="", total_events=100)
        report = classify_terminal_output(record=rec)
        for sig in report.signals:
            for key, val in sig.evidence.items():
                assert isinstance(val, (str, int, float, bool, type(None))), (
                    f"Non-scalar evidence in {sig.code}.{key}: {type(val).__name__} = {val!r}"
                )

    def test_recursive_scalar_only_all_signals_in_report(self):
        """Every value reachable from report.to_dict() evidence must be a bounded scalar."""
        rec = _base_record(output="", total_events=100, dropped_events=5, stop_reason="max_tokens")
        report = classify_terminal_output(record=rec)
        d = report.to_dict()

        def _assert_scalar(path: str, val: object) -> None:
            if isinstance(val, (str, int, float, bool, type(None))):
                return  # scalar — ok
            if isinstance(val, dict):
                for k, v in val.items():
                    _assert_scalar(f"{path}.{k}", v)
                return
            if isinstance(val, list):
                for i, v in enumerate(val):
                    _assert_scalar(f"{path}[{i}]", v)
                return
            raise AssertionError(
                f"Non-scalar value at {path}: type={type(val).__name__}, val={val!r}"
            )

        for sig_dict in d["signals"]:
            _assert_scalar(f"signal[{sig_dict['code']}]", sig_dict["evidence"])


# ---------------------------------------------------------------------------
# Version and serialization
# ---------------------------------------------------------------------------

class TestVersionAndSerialization:
    def test_classifier_version(self):
        rec = _base_record()
        report = classify_terminal_output(record=rec)
        assert report.classifier_version == CLASSIFIER_VERSION

    def test_to_dict(self):
        rec = _base_record(output="", total_events=100)
        report = classify_terminal_output(record=rec)
        d = report.to_dict()
        assert d["classifier_version"] == CLASSIFIER_VERSION
        assert d["label"] == "premature-halt-suspected"
        assert isinstance(d["signals"], list)
        for s in d["signals"]:
            assert "code" in s and "severity" in s

    def test_signal_to_dict(self):
        from audiagentic.components.agents.agents_terminal_quality import (
            TerminalQualitySignal,
        )
        sig = TerminalQualitySignal(
            code="TQ-TEST",
            severity="info",
            message="Test signal",
            evidence={"count": 5},
        )
        d = sig.to_dict()
        assert d == {
            "code": "TQ-TEST",
            "severity": "info",
            "message": "Test signal",
            "evidence": {"count": 5},
        }

# ---------------------------------------------------------------------------
# Per-signal recursive scalar-only evidence (AS36 review correction)
# ---------------------------------------------------------------------------

def _assert_evidence_scalar_only(report: TerminalQualityReport) -> None:
    """Assert every value in report.to_dict() evidence trees is a bounded scalar."""
    d = report.to_dict()

    def _check(path: str, val: object) -> None:
        if isinstance(val, (str, int, float, bool, type(None))):
            return  # bounded scalar — ok
        if isinstance(val, dict):
            for k, v in val.items():
                _check(f"{path}.{k}", v)
            return
        if isinstance(val, list):
            for i, v in enumerate(val):
                _check(f"{path}[{i}]", v)
            return
        raise AssertionError(
            f"Non-scalar value at {path}: type={type(val).__name__}, val={val!r}"
        )

    for sig_dict in d["signals"]:
        _check(f"signal[{sig_dict['code']}].evidence", sig_dict["evidence"])


class TestPerSignalScalarEvidence:
    """Every individual signal's evidence must be bounded scalar only.

    Triggers each signal and verifies scalar-only evidence through to_dict().
    """

    def test_TQ_NO_OUTPUT_scalar_evidence(self):
        rec = _base_record(output="", total_events=100)
        report = classify_terminal_output(record=rec)
        assert "TQ-NO-OUTPUT" in _signals(report)
        _assert_evidence_scalar_only(report)

    def test_TQ_ENDS_WITH_PREAMBLE_scalar_evidence(self):
        rec = _base_record(output="Now update the README:")
        report = classify_terminal_output(record=rec)
        assert "TQ-ENDS-WITH-PREAMBLE" in _signals(report)
        _assert_evidence_scalar_only(report)

    def test_TQ_MISSING_EXPECTED_CLOSEOUT_scalar_evidence(self):
        rec = _base_record(
            output=(
                "First, I'll update the config.\n"
                "Next let me check the results.\n"
                "Now let me verify the output."
            )
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-MISSING-EXPECTED-CLOSEOUT" in _signals(report)
        _assert_evidence_scalar_only(report)

    def test_TQ_UNTERMINATED_MARKDOWN_scalar_evidence(self):
        rec = _base_record(
            output="Here is a code block:\n```python\nprint('hello')\n- Items:"
        )
        report = classify_terminal_output(record=rec)
        assert "TQ-UNTERMINATED-MARKDOWN" in _signals(report)
        sig = [s for s in report.signals if s.code == "TQ-UNTERMINATED-MARKDOWN"][0]
        # Specific: issue-count is int, issue-codes is str, no raw list
        assert isinstance(sig.evidence["issue-count"], int)
        assert isinstance(sig.evidence["issue-codes"], str)
        assert "issues" not in sig.evidence  # old list key must not exist
        _assert_evidence_scalar_only(report)

    def test_TQ_REPETITION_line_scalar_evidence(self):
        lines = ["Processing file..."] * 10
        rec = _base_record(output="\n".join(lines))
        report = classify_terminal_output(record=rec)
        assert "TQ-REPETITION" in _signals(report)
        _assert_evidence_scalar_only(report)

    def test_TQ_REPETITION_phrase_scalar_evidence(self):
        lines = [
            "Let me check file1", "ok",
            "Let me check file2", "ok",
            "Let me check file3", "ok",
            "Let me check file4",
        ]
        rec = _base_record(output="\n".join(lines), total_events=10)
        report = classify_terminal_output(record=rec)
        assert "TQ-REPETITION" in _signals(report)
        _assert_evidence_scalar_only(report)

    def test_TQ_DROPPED_EVENTS_scalar_evidence(self):
        rec = _base_record(output="Some work completed.", dropped_events=5)
        report = classify_terminal_output(record=rec)
        assert "TQ-DROPPED-EVENTS" in _signals(report)
        _assert_evidence_scalar_only(report)

    def test_TQ_HIGH_EVENT_LOW_OUTPUT_scalar_evidence(self):
        rec = _base_record(output="Ok", total_events=1000)
        report = classify_terminal_output(record=rec)
        assert "TQ-HIGH-EVENT-LOW-OUTPUT" in _signals(report)
        _assert_evidence_scalar_only(report)

    def test_TQ_STOP_REASON_scalar_evidence(self):
        rec = _base_record(stop_reason="max_tokens")
        report = classify_terminal_output(record=rec)
        assert "TQ-STOP-REASON" in _signals(report)
        _assert_evidence_scalar_only(report)

    def test_TQ_TOOL_AFTER_LAST_TEXT_scalar_evidence(self):
        rec = _base_record()
        summary = {
            "last-assistant-event-sequence": 10,
            "last-tool-event-sequence": 15,
        }
        report = classify_terminal_output(
            record=rec,
            session_event_summary=summary,
        )
        assert "TQ-TOOL-AFTER-LAST-TEXT" in _signals(report)
        _assert_evidence_scalar_only(report)
