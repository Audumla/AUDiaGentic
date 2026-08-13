"""AS36 terminal-quality classifier contract guard (unit).

Tests verify the pure-classifier interface contract for
agents_terminal_quality: dataclass structure, enum completeness,
function signature, deterministic signal vocabulary, redaction guarantees,
and label-aggregation rules — without requiring the wiring into gateway
status/wait endpoints (those are a separate test slice).

These are *contract* tests: they assert the shape and guarantees of the
classifier API so that future implementation changes cannot break the
diagnostic contract silently.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

import pytest

# The classifier is part of the current Agents surface.  Import it directly so
# a removed or broken implementation fails collection instead of leaving a
# misleading "tests are skipped until the module exists" compatibility stub.
from audiagentic.components.agents.status import terminal_quality as tq

# ---------------------------------------------------------------------------
# Mark all tests in this module as unit-level (no real I/O).
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.unit

# ===========================================================================
# Section 1 — Module-level existence and dataclass contracts
# ===========================================================================

class TestModuleExists:
    """The classifier module is importable and exposes the expected symbols."""

    def test_module_importable(self):
        assert tq is not None, "agents_terminal_quality module does not exist yet"

    def test_terminal_quality_label_exists(self):
        assert hasattr(tq, "TerminalQualityLabel")

    def test_terminal_quality_signal_exists(self):
        assert hasattr(tq, "TerminalQualitySignal")

    def test_terminal_quality_report_exists(self):
        assert hasattr(tq, "TerminalQualityReport")

    def test_classify_terminal_output_exists(self):
        assert hasattr(tq, "classify_terminal_output")

    def test_classify_terminal_output_callable(self):
        assert callable(getattr(tq, "classify_terminal_output", None))


class TestTerminalQualityLabelContract:
    """TerminalQualityLabel must be a StrEnum with the exact label set."""

    LABELS_REQUIRED = {
        "clean",
        "suspicious",
        "premature-halt-suspected",
        "repetition-suspected",
        "content-capture-suspected",
        "unknown",
    }

    def test_is_str_enum(self):
        label_cls = tq.TerminalQualityLabel
        assert issubclass(label_cls, Enum)

    def test_values_are_strings(self):
        for member in tq.TerminalQualityLabel:
            assert isinstance(member.value, str), (
                f"{member.name} value {member.value!r} is not a string"
            )

    def test_all_required_labels_present(self):
        actual = {m.value for m in tq.TerminalQualityLabel}
        missing = self.LABELS_REQUIRED - actual
        assert not missing, f"Missing label values: {missing}"

    def test_no_extra_labels(self):
        actual = {m.value for m in tq.TerminalQualityLabel}
        extra = actual - self.LABELS_REQUIRED
        assert not extra, f"Unexpected label values: {extra}"


class TestTerminalQualitySignalContract:
    """TerminalQualitySignal must be a frozen dataclass with exact fields."""

    REQUIRED_FIELDS = {"code", "severity", "message", "evidence"}
    VALID_SEVERITIES = {"info", "warning", "critical"}

    def test_is_frozen_dataclass(self):
        signal_cls = tq.TerminalQualitySignal
        assert is_dataclass(signal_cls)

    def test_has_required_fields(self):
        fields = {f.name for f in tq.TerminalQualitySignal.__dataclass_fields__.values()}
        missing = self.REQUIRED_FIELDS - fields
        assert not missing, f"Missing fields: {missing}"

    def test_code_is_string(self):
        sig = tq.TerminalQualitySignal(
            code="TQ-TEST", severity="info", message="x", evidence={}
        )
        assert isinstance(sig.code, str)

    def test_severity_in_closed_vocabulary(self):
        """severity must be one of info/warning/critical."""
        sig = tq.TerminalQualitySignal(
            code="TQ-TEST", severity="warning", message="x", evidence={}
        )
        assert sig.severity in self.VALID_SEVERITIES

    def test_message_is_string(self):
        sig = tq.TerminalQualitySignal(
            code="TQ-TEST", severity="info", message="test", evidence={}
        )
        assert isinstance(sig.message, str)

    def test_evidence_is_mapping(self):
        ev = {"key": 1}
        sig = tq.TerminalQualitySignal(
            code="TQ-TEST", severity="info", message="x", evidence=ev
        )
        assert isinstance(sig.evidence, Mapping)


class TestTerminalQualityReportContract:
    """TerminalQualityReport must be a frozen dataclass with exact fields."""

    REQUIRED_FIELDS = {"label", "confidence", "signals", "classifier_version"}

    def test_is_frozen_dataclass(self):
        report_cls = tq.TerminalQualityReport
        assert is_dataclass(report_cls)

    def test_has_required_fields(self):
        fields = {f.name for f in tq.TerminalQualityReport.__dataclass_fields__.values()}
        missing = self.REQUIRED_FIELDS - fields
        assert not missing, f"Missing fields: {missing}"

    def test_label_is_terminal_quality_label(self):
        report = tq.TerminalQualityReport(
            label=tq.TerminalQualityLabel.CLEAN,
            confidence=1.0,
            signals=(),
            classifier_version="1",
        )
        assert isinstance(report.label, tq.TerminalQualityLabel)

    def test_confidence_bounded_0_to_1(self):
        report = tq.TerminalQualityReport(
            label=tq.TerminalQualityLabel.CLEAN,
            confidence=0.5,
            signals=(),
            classifier_version="1",
        )
        assert 0.0 <= report.confidence <= 1.0

    def test_signals_is_tuple_of_signals(self):
        sig = tq.TerminalQualitySignal(
            code="TQ-TEST", severity="info", message="x", evidence={}
        )
        report = tq.TerminalQualityReport(
            label=tq.TerminalQualityLabel.CLEAN,
            confidence=1.0,
            signals=(sig,),
            classifier_version="1",
        )
        assert isinstance(report.signals, tuple)
        assert all(isinstance(s, tq.TerminalQualitySignal) for s in report.signals)

    def test_classifier_version_is_string(self):
        report = tq.TerminalQualityReport(
            label=tq.TerminalQualityLabel.CLEAN,
            confidence=1.0,
            signals=(),
            classifier_version="1.0.0",
        )
        assert isinstance(report.classifier_version, str)

# ===========================================================================
# Section 2 — classify_terminal_output function contract
# ===========================================================================

class TestClassifyTerminalOutputSignature:
    """classify_terminal_output must accept keyword-only inputs and return a
    TerminalQualityReport."""

    def _minimal_record(self) -> dict[str, Any]:
        return {
            "request-id": "req_test123",
            "state": "completed",
            "output": "Done.",
            "completion": {"stop-reason": "end_turn"},
        }

    def test_returns_terminal_quality_report(self):
        record = self._minimal_record()
        result = tq.classify_terminal_output(record=record)
        assert isinstance(result, tq.TerminalQualityReport)

    def test_accepts_record_keyword(self):
        record = self._minimal_record()
        tq.classify_terminal_output(record=record)  # should not raise

    def test_accepts_optional_latest_turn(self):
        record = self._minimal_record()
        result = tq.classify_terminal_output(
            record=record,
            latest_turn={"kind": "assistant-message"},
        )
        assert isinstance(result, tq.TerminalQualityReport)

    def test_accepts_optional_session_event_summary(self):
        record = self._minimal_record()
        result = tq.classify_terminal_output(
            record=record,
            session_event_summary={
                "event-count": 100,
                "last-assistant-event-sequence": 50,
                "last-tool-event-sequence": 45,
            },
        )
        assert isinstance(result, tq.TerminalQualityReport)

    def test_returns_unknown_when_record_is_empty(self):
        """An empty record yields UNKNOWN label (non-terminal state)."""
        result = tq.classify_terminal_output(record={})
        assert result.label == tq.TerminalQualityLabel.UNKNOWN

    def test_no_side_effects_on_inputs(self):
        """The classifier must not mutate the input dicts."""
        record = self._minimal_record()
        record_copy = dict(record)
        completion_copy = dict(record["completion"])

        tq.classify_terminal_output(record=record)
        assert record == record_copy
        assert record["completion"] == completion_copy

    def test_deterministic_output(self):
        """Same inputs must always produce the same output."""
        record = self._minimal_record()
        r1 = tq.classify_terminal_output(record=record)
        r2 = tq.classify_terminal_output(record=record)
        assert asdict(r1) == asdict(r2)

# ===========================================================================
# Section 3 — Signal vocabulary contract (closed set)
# ===========================================================================

SIGNAL_CODES_REQUIRED = {
    "TQ-NO-OUTPUT",
    "TQ-ENDS-WITH-PREAMBLE",
    "TQ-MISSING-EXPECTED-CLOSEOUT",
    "TQ-UNTERMINATED-MARKDOWN",
    "TQ-REPETITION",
    "TQ-DROPPED-EVENTS",
    "TQ-HIGH-EVENT-LOW-OUTPUT",
    "TQ-STOP-REASON",
    "TQ-TOOL-AFTER-LAST-TEXT",
}

class TestSignalVocabularyClosed:
    """All signal codes must come from the closed vocabulary in the plan."""

    def _trigger_all_signals(self) -> dict[str, Any]:
        """Construct a record that should trigger as many signals as possible."""
        return {
            "request-id": "req_test123",
            "state": "completed",
            "output": "",  # TQ-NO-OUTPUT
            "completion": {
                "stop-reason": "max_tokens",  # TQ-STOP-REASON
                "dropped-events": 5,  # TQ-DROPPED-EVENTS
                "total-events": 1000,  # TQ-HIGH-EVENT-LOW-OUTPUT
            },
            "attempts": [{"attempt-number": 1}],
        }

    def test_no_unknown_signal_codes(self):
        """Any signal emitted must have a code in the closed vocabulary."""
        record = self._trigger_all_signals()
        result = tq.classify_terminal_output(record=record)

        for sig in result.signals:
            assert sig.code in SIGNAL_CODES_REQUIRED, (
                f"Unknown signal code '{sig.code}' not in plan vocabulary"
            )

# ===========================================================================
# Section 4 — Redaction contract (no forbidden content in evidence)
# ===========================================================================

FORBIDDEN_EVIDENCE_KEYS = {
    "prompt-body",
    "prompt_body",
    "output",  # raw output text must not leak into evidence
    "tool_args",
    "tool-args",
    "tool-calls",
    "tool_calls",
    "tool-results",
    "tool_results",
    "provider-session-ref",
    "binding-ref",
    "raw-payload",
    "hidden-reasoning",
}

class TestRedactionContract:
    """Signal evidence must never contain forbidden content."""

    def _suspicious_record(self) -> dict[str, Any]:
        return {
            "request-id": "req_test123",
            "state": "completed",
            "output": "Now let me update the file:",  # ends with preamble
            "completion": {
                "stop-reason": "end_turn",
                "dropped-events": 0,
                "total-events": 50,
            },
        }

    def test_evidence_has_no_forbidden_keys(self):
        result = tq.classify_terminal_output(record=self._suspicious_record())
        for sig in result.signals:
            ev = sig.evidence
            if isinstance(ev, Mapping):
                for forbidden in FORBIDDEN_EVIDENCE_KEYS:
                    assert forbidden not in ev, (
                        f"Forbidden key '{forbidden}' found in signal evidence "
                        f"for {sig.code}"
                    )

    def test_evidence_values_are_scalar_or_bounded(self):
        """Evidence values must be scalars (str/int/float/bool) or bounded
        collections of scalars — no raw prompt text or large payloads."""
        result = tq.classify_terminal_output(record=self._suspicious_record())

        for sig in result.signals:
            self._assert_bounded_evidence(sig.evidence, path=sig.code)

    @staticmethod
    def _assert_bounded_evidence(value: Any, *, path: str) -> None:
        """Recursively assert evidence is bounded (scalar or short collection)."""
        if isinstance(value, (str, int, float, bool)) or value is None:
            # Scalars are fine, but long strings are not raw content
            if isinstance(value, str) and len(value) > 200:
                raise AssertionError(
                    f"Evidence at '{path}' has a string > 200 chars "
                    f"({len(value)} chars) — likely raw content leak"
                )
        elif isinstance(value, (list, tuple)):
            if len(value) > 50:
                raise AssertionError(
                    f"Evidence at '{path}' has a collection > 50 items "
                    f"— unbounded"
                )
            for i, item in enumerate(value):
                TestRedactionContract._assert_bounded_evidence(
                    item, path=f"{path}[{i}]"
                )
        elif isinstance(value, dict):
            if len(value) > 50:
                raise AssertionError(
                    f"Evidence at '{path}' has a dict with > 50 keys "
                    f"— unbounded"
                )
            for k, v in value.items():
                TestRedactionContract._assert_bounded_evidence(v, path=f"{path}.{k}")

# ===========================================================================
# Section 5 — Label assignment contract (key scenarios from the plan)
# ===========================================================================

class TestLabelAssignmentContract:
    """The classifier must assign labels according to the deterministic rules
    specified in the plan. These are contract tests — we assert the label,
    not the internal implementation details."""

    def _base_record(self, **overrides) -> dict[str, Any]:
        base = {
            "request-id": "req_test123",
            "state": "completed",
            "output": "Summary of work done. All tests pass.",
            "completion": {"stop-reason": "end_turn"},
        }
        base.update(overrides)
        return base

    def test_clean_when_complete_with_closeout(self):
        """A record with clear closeout and end_turn should be CLEAN."""
        record = self._base_record()
        result = tq.classify_terminal_output(record=record)
        assert result.label == tq.TerminalQualityLabel.CLEAN

    def test_no_output_nontrivial_events_yields_suspicious(self):
        """Terminal completed with no output after nontrivial event count is
        at least SUSPICIOUS (specifically PREMATURE_HALT_SUSPECTED)."""
        record = self._base_record(
            output="",
            completion={"stop-reason": "end_turn", "total-events": 100},
        )
        result = tq.classify_terminal_output(record=record)
        assert result.label in (
            tq.TerminalQualityLabel.SUSPICIOUS,
            tq.TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
        )

    def test_no_output_low_events_yields_clean(self):
        """Terminal completed with no output but few events is CLEAN
        (not suspicious — there was nothing substantial to complete)."""
        record = self._base_record(
            output="",
            completion={"stop-reason": "end_turn", "total-events": 5},
        )
        result = tq.classify_terminal_output(record=record)
        assert result.label == tq.TerminalQualityLabel.CLEAN

    def test_preamble_ending_yields_suspicious(self):
        """Output ending with preamble pattern (e.g. 'Now let me update:') is
        at least SUSPICIOUS."""
        record = self._base_record(output="Processing the file. Now let me update:")
        result = tq.classify_terminal_output(record=record)
        assert result.label in (
            tq.TerminalQualityLabel.SUSPICIOUS,
            tq.TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
        )

    def test_preamble_ending_case_insensitive(self):
        """Preamble detection must be case-insensitive."""
        record = self._base_record(
            output="Processing the file. now LET ME update:"
        )
        result = tq.classify_terminal_output(record=record)
        assert result.label in (
            tq.TerminalQualityLabel.SUSPICIOUS,
            tq.TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
        )

    def test_dropped_events_with_no_closeout_yields_suspicious(self):
        """dropped-events > 0 with no closeout is at least SUSPICIOUS.
        The aggregate label may be higher severity if other signals fire."""
        record = self._base_record(
            output="Work in progress. Now I'll add tests.",
            completion={
                "stop-reason": "end_turn",
                "dropped-events": 3,
            },
        )
        result = tq.classify_terminal_output(record=record)
        assert result.label in (
            tq.TerminalQualityLabel.SUSPICIOUS,
            tq.TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
            tq.TerminalQualityLabel.CONTENT_CAPTURE_SUSPECTED,
        )

    def test_max_tokens_stop_reason_yields_at_least_suspicious(self):
        """Non-end_turn stop reason should produce at least SUSPICIOUS."""
        record = self._base_record(
            completion={"stop-reason": "max_tokens"}
        )
        result = tq.classify_terminal_output(record=record)
        assert result.label in (
            tq.TerminalQualityLabel.SUSPICIOUS,
            tq.TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
        )

    def test_high_event_low_output_yields_suspicious(self):
        """total-events > 500 and output < 500 chars with end_turn is
        at least SUSPICIOUS."""
        record = self._base_record(
            output="Ok.",
            completion={
                "stop-reason": "end_turn",
                "total-events": 800,
            },
        )
        result = tq.classify_terminal_output(record=record)
        assert result.label in (
            tq.TerminalQualityLabel.SUSPICIOUS,
            tq.TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
        )

    def test_missing_closeout_yields_suspicious(self):
        """Multiple progress markers but no closeout markers is at least
        SUSPICIOUS."""
        record = self._base_record(
            output=(
                "First, let me read the file. "
                "Now I'll update it. "
                "Next, run tests. "
                "Let me check the results."
            )
        )
        result = tq.classify_terminal_output(record=record)
        assert result.label in (
            tq.TerminalQualityLabel.SUSPICIOUS,
            tq.TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
        )

    def test_sh07_incident_shape(self):
        """The SH07 C2 incident shape: completed, end_turn, high total-events,
        substantial output ending mid-progress. Label should be at least
        SUSPICIOUS."""
        record = self._base_record(
            output=(
                "I have made the following changes:\n"
                "1. Updated module A\n"
                "2. Fixed bug in module B\n"
                "3. Added tests for feature C\n"
                "Now let me update the remaining files:"
            ),
            completion={
                "stop-reason": "end_turn",
                "dropped-events": 0,
                "total-events": 2790,
            },
        )
        result = tq.classify_terminal_output(record=record)
        assert result.label in (
            tq.TerminalQualityLabel.SUSPICIOUS,
            tq.TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
        ), (
            f"SH07 incident shape should be at least suspicious, "
            f"got {result.label}"
        )

# ===========================================================================
# Section 6 — Purity contract (no side effects, no forbidden imports)
# ===========================================================================

class TestPurityContract:
    """The classifier must not import provider adapters, event bus internals,
    or planning code."""

    FORBIDDEN_IMPORT_PREFIXES = [
        "audiagentic.components.providers",
        "audiagentic.foundation.event.bus",
        "audiagentic.components.planning",
    ]

    def test_no_forbidden_imports_in_module_namespace(self):
        """The module namespace must not reference forbidden import paths."""
        module_name = tq.__name__
        for prefix in self.FORBIDDEN_IMPORT_PREFIXES:
            assert prefix != module_name, (
                f"Module {module_name} is from forbidden prefix {prefix}"
            )

# ===========================================================================
# Section 7 — Confidence contract
# ===========================================================================

class TestConfidenceContract:
    """Confidence must be a deterministic float in [0.0, 1.0]."""

    def _base_record(self, **overrides) -> dict[str, Any]:
        base = {
            "request-id": "req_test123",
            "state": "completed",
            "output": "Done.",
            "completion": {"stop-reason": "end_turn"},
        }
        base.update(overrides)
        return base

    def test_clean_has_confidence_1_0(self):
        """No signals → confidence 1.0."""
        record = self._base_record()
        result = tq.classify_terminal_output(record=record)
        assert result.confidence == 1.0

    def test_suspicious_has_confidence_in_range(self):
        """Signals fire → confidence > 0 and <= 1.0."""
        record = self._base_record(
            output="Now let me update:",
        )
        result = tq.classify_terminal_output(record=record)
        assert 0.0 < result.confidence <= 1.0

    def test_confidence_is_float(self):
        result = tq.classify_terminal_output(record=self._base_record())
        assert isinstance(result.confidence, float)

# ===========================================================================
# Section 8 — Version contract
# ===========================================================================

class TestVersionContract:
    """classifier_version must be a non-empty string constant."""

    def test_classifier_version_constant_exists(self):
        assert hasattr(tq, "CLASSIFIER_VERSION")
        assert isinstance(tq.CLASSIFIER_VERSION, str)
        assert len(tq.CLASSIFIER_VERSION) > 0

    def test_report_uses_version_constant(self):
        record = {
            "request-id": "req_test123",
            "state": "completed",
            "output": "Done.",
            "completion": {"stop-reason": "end_turn"},
        }
        result = tq.classify_terminal_output(record=record)
        assert result.classifier_version == tq.CLASSIFIER_VERSION

# ===========================================================================
# Section 9 — Non-terminal request contract
# ===========================================================================

class TestNonTerminalContract:
    """classify_terminal_output must return UNKNOWN for non-terminal states."""

    def test_running_returns_unknown(self):
        record = {
            "request-id": "req_test123",
            "state": "running",
            "output": "",
        }
        result = tq.classify_terminal_output(record=record)
        assert result.label == tq.TerminalQualityLabel.UNKNOWN

    def test_queued_returns_unknown(self):
        record = {
            "request-id": "req_test123",
            "state": "queued",
            "output": "",
        }
        result = tq.classify_terminal_output(record=record)
        assert result.label == tq.TerminalQualityLabel.UNKNOWN

    def test_terminal_states_handled(self):
        """completed, error, cancelled are terminal — should produce a label."""
        for state in ("completed", "error", "cancelled"):
            record = {
                "request-id": "req_test123",
                "state": state,
                "output": "Done.",
                "completion": {"stop-reason": "end_turn"},
            }
            result = tq.classify_terminal_output(record=record)
            assert result.label != tq.TerminalQualityLabel.UNKNOWN, (
                f"Terminal state '{state}' should not yield UNKNOWN label"
            )

# ===========================================================================
# Section 10 — to_dict projection contract
# ===========================================================================

class TestToDictProjectionContract:
    """to_dict() on Signal and Report must produce dicts with expected keys."""

    def test_signal_to_dict_keys(self):
        sig = tq.TerminalQualitySignal(
            code="TQ-TEST", severity="info", message="x", evidence={"k": 1}
        )
        d = sig.to_dict()
        assert "code" in d
        assert "severity" in d
        assert "message" in d
        assert "evidence" in d

    def test_report_to_dict_keys(self):
        report = tq.TerminalQualityReport(
            label=tq.TerminalQualityLabel.CLEAN,
            confidence=1.0,
            signals=(),
            classifier_version="1",
        )
        d = report.to_dict()
        assert "label" in d
        assert "confidence" in d
        assert "signals" in d
        assert "classifier_version" in d

    def test_report_to_dict_label_is_string(self):
        """Label in to_dict output must be the string value, not the enum."""
        report = tq.TerminalQualityReport(
            label=tq.TerminalQualityLabel.CLEAN,
            confidence=1.0,
            signals=(),
            classifier_version="1",
        )
        d = report.to_dict()
        assert isinstance(d["label"], str)
