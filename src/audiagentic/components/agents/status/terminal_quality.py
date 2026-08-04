"""Pure deterministic classifier for terminal agent output quality.

Diagnostic metadata only — does not change request state, auto-resubmit, or
read raw prompt/tool payloads. See plan item AS36.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# ---------------------------------------------------------------------------
# Public types (frozen, immutable)
# ---------------------------------------------------------------------------

class TerminalQualityLabel(StrEnum):
    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    PREMATURE_HALT_SUSPECTED = "premature-halt-suspected"
    REPETITION_SUSPECTED = "repetition-suspected"
    CONTENT_CAPTURE_SUSPECTED = "content-capture-suspected"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TerminalQualitySignal:
    code: str  # closed vocabulary, e.g. "TQ-MISSING-SUMMARY"
    severity: str  # "info" | "warning" | "critical"
    message: str  # short operator text, no raw prompt/tool payload
    evidence: Mapping[str, Any]  # bounded scalar/redacted evidence only

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "evidence": dict(self.evidence),
        }


@dataclass(frozen=True)
class TerminalQualityReport:
    label: TerminalQualityLabel
    confidence: float  # 0.0 .. 1.0 deterministic heuristic confidence
    signals: tuple[TerminalQualitySignal, ...]
    classifier_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label.value,
            "confidence": self.confidence,
            "signals": [s.to_dict() for s in self.signals],
            "classifier_version": self.classifier_version,
        }


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

CLASSIFIER_VERSION = "1.0.0-as36"

# ---------------------------------------------------------------------------
# Thresholds (tunable; kept at module level for testability)
# ---------------------------------------------------------------------------

# Minimum output length after nontrivial event count to avoid TQ-NO-OUTPUT
_OUTPUT_MIN_CHARS = 50
# Event counts above which we consider the session "nontrivial"
_NONTRIVIAL_EVENT_COUNT = 20
# Total-events above which low output is suspicious
_HIGH_EVENT_THRESHOLD = 500
_LOW_OUTPUT_THRESHOLD_CHARS = 500
# Repetition detection
_REPETITION_LINE_THRESHOLD = 8  # identical lines repeated >= N times
_REPETITION_PHRASE_THRESHOLD = 4  # same progress phrase >= N times
_REPETITION_SUBSTANTIVE_MIN = 30  # chars of non-repeated text between repeats before it doesn't count

# ---------------------------------------------------------------------------
# Preamble / closeout patterns (case-insensitive)
# ---------------------------------------------------------------------------

_PREAMBLE_PATTERNS = [
    r":\s*$",                              # line ending with colon (task intro)
    r"\bnow let me\b",
    r"\blet me\b",
    r"^next,?\s+",                         # "Next," / "Next" at start of line only
    r"^first,?\s+",                        # "First," / "First" at start of line
    r"\bi will\b",
    r"\bi'll\b",
    r"\bupdat(ing|e)\b",
    r"\bnow update\b",
    r"\bnow add\b",
    r"\bnow run\b",
]
_PREAMBLE_RE = re.compile("|".join(_PREAMBLE_PATTERNS), re.IGNORECASE | re.MULTILINE)

_CLOSEOUT_MARKERS = [
    "summary",
    "validation",
    "self-review",
    "findings",
    "result",
]

_PROGRESS_MARKERS = [
    r"\bnow\b",
    r"\blet me\b",
    r"^first,?\s+",
    r"^next,?\s+",
    r"\brun tests\b",
]

# Additional closeout phrases that are more specific than single words
_CLOSEOUT_PHRASES = [
    "tests passed",
    "all tests",
    "tests complete",
    r"^done\b",
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_output(record: Mapping[str, Any]) -> str:
    """Extract the output string from a request record (may be None/empty)."""
    return str(record.get("output") or "")

def _safe_stop_reason(record: Mapping[str, Any]) -> str | None:
    completion = record.get("completion") or {}
    return completion.get("stop-reason") if isinstance(completion, Mapping) else None

def _safe_dropped_events(record: Mapping[str, Any]) -> int:
    completion = record.get("completion") or {}
    val = completion.get("dropped-events") if isinstance(completion, Mapping) else 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0

def _safe_total_events(record: Mapping[str, Any]) -> int:
    completion = record.get("completion") or {}
    val = completion.get("total-events") if isinstance(completion, Mapping) else 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0

def _is_terminal_state(state: str | None) -> bool:
    return state in {"completed", "error", "cancelled"}

# ---------------------------------------------------------------------------
# Signal emitters
# ---------------------------------------------------------------------------

def _check_no_output(record: Mapping[str, Any]) -> TerminalQualitySignal | None:
    output = _safe_output(record)
    total_events = _safe_total_events(record)
    if len(output) >= _OUTPUT_MIN_CHARS or total_events < _NONTRIVIAL_EVENT_COUNT:
        return None
    return TerminalQualitySignal(
        code="TQ-NO-OUTPUT",
        severity="critical",
        message="Terminal completed with no output after nontrivial activity.",
        evidence={
            "output-length": len(output),
            "total-events": total_events,
        },
    )

def _check_ends_with_preamble(record: Mapping[str, Any]) -> TerminalQualitySignal | None:
    output = _safe_output(record)
    if not output.strip():
        return None
    last_line = output.rstrip().splitlines()[-1].rstrip()
    # Strip leading markdown punctuation (bullets, dashes)
    stripped = re.sub(r"^[-*+]\s*", "", last_line).strip()
    if _PREAMBLE_RE.search(stripped):
        return TerminalQualitySignal(
            code="TQ-ENDS-WITH-PREAMBLE",
            severity="warning",
            message="Last non-empty output line ends with a progress/preamble pattern.",
            evidence={
                "last-line-length": len(last_line),
            },
        )
    return None

def _check_missing_closeout(record: Mapping[str, Any]) -> TerminalQualitySignal | None:
    output = _safe_output(record)
    if not output.strip():
        return None
    lower = output.lower()
    progress_count = sum(
        1 for pat in _PROGRESS_MARKERS if re.search(pat, lower, re.MULTILINE)
    )
    closeout_count = 0
    for marker in _CLOSEOUT_MARKERS:
        if re.search(r"\b" + re.escape(marker) + r"\b", lower):
            closeout_count += 1
    for phrase in _CLOSEOUT_PHRASES:
        if re.search(phrase, lower, re.MULTILINE | re.IGNORECASE):
            closeout_count += 1
    # Only flag when there are multiple progress markers but no closeout
    if progress_count >= 2 and closeout_count == 0:
        return TerminalQualitySignal(
            code="TQ-MISSING-EXPECTED-CLOSEOUT",
            severity="warning",
            message="Output has multiple progress markers but no closeout marker.",
            evidence={
                "progress-marker-count": progress_count,
                "closeout-marker-count": closeout_count,
            },
        )
    return None

def _check_unterminated_markdown(record: Mapping[str, Any]) -> TerminalQualitySignal | None:
    output = _safe_output(record)
    if not output.strip():
        return None
    issues = []
    # Odd number of fenced code blocks (``` lines)
    fence_count = len(re.findall(r"^```", output, re.MULTILINE))
    if fence_count % 2 != 0:
        issues.append(f"odd-fences={fence_count}")

    # Bullet/list line ending with an unfinished colon (at end of text, no content after)
    if re.search(r"^[-*+]\s.*:\s*$", output, re.MULTILINE):
        issues.append("unfinished-bullet-colon")

    # Table header without row: "---+" or similar separator with no following data row
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\|?\s*[-:|]+\s*\|?\s*$", line.strip()):
            # potential table separator — check next non-empty line has data
            found_data = False
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    if "|" in lines[j]:
                        found_data = True
                    break
            if not found_data:
                issues.append("table-header-no-data-row")

    if issues:
        issue_codes = ",".join(issues[:5])  # bounded to 5 codes max
        return TerminalQualitySignal(
            code="TQ-UNTERMINATED-MARKDOWN",
            severity="info",
            message="Output contains unterminated or malformed markdown structures.",
            evidence={
                "issue-count": len(issues),
                "issue-codes": issue_codes,
            },
        )
    return None

def _check_repetition(record: Mapping[str, Any]) -> TerminalQualitySignal | None:
    output = _safe_output(record)
    if not output.strip():
        return None
    lines = [l.rstrip() for l in output.splitlines()]

    # Check identical line repetition
    from collections import Counter
    line_counts = Counter(lines)
    max_rep = 0
    for count in line_counts.values():
        if count > max_rep:
            max_rep = count

    if max_rep >= _REPETITION_LINE_THRESHOLD:
        return TerminalQualitySignal(
            code="TQ-REPETITION",
            severity="warning",
            message="Repeated identical lines detected above threshold.",
            evidence={
                "max-repeated-line-count": max_rep,
                "total-lines": len(lines),
            },
        )

    # Check repeated progress phrases with little intervening substantive text
    for pat in _PREAMBLE_PATTERNS:
        phrase_lines = [
            i
            for i, l in enumerate(lines)
            if re.search(pat, l, re.IGNORECASE | re.MULTILINE)
        ]
        if len(phrase_lines) >= _REPETITION_PHRASE_THRESHOLD:
            # Check intervening text between consecutive matches is small
            substantive_gaps = 0
            for k in range(len(phrase_lines) - 1):
                start = phrase_lines[k] + 1
                end = phrase_lines[k + 1]
                intervening = "".join(lines[start:end]).strip()
                if len(intervening) > _REPETITION_SUBSTANTIVE_MIN:
                    substantive_gaps += 1
            # If few gaps have substantive text, flag it
            if substantive_gaps < len(phrase_lines) / 2:
                return TerminalQualitySignal(
                    code="TQ-REPETITION",
                    severity="warning",
                    message=f"Repeated progress phrase detected (>= {len(phrase_lines)} occurrences).",
                    evidence={
                        "occurrence-count": len(phrase_lines),
                        "substantive-gaps": substantive_gaps,
                    },
                )

    return None

def _check_dropped_events(record: Mapping[str, Any]) -> TerminalQualitySignal | None:
    dropped = _safe_dropped_events(record)
    if dropped == 0:
        return None
    output = _safe_output(record)
    lower = output.lower()
    has_closeout = any(
        re.search(r"\b" + re.escape(m) + r"\b", lower) for m in _CLOSEOUT_MARKERS
    )
    if not has_closeout:
        has_closeout = any(
            re.search(p, lower, re.MULTILINE | re.IGNORECASE)
            for p in _CLOSEOUT_PHRASES
        )
    severity = "warning"
    if not has_closeout:
        severity = "critical"
    return TerminalQualitySignal(
        code="TQ-DROPPED-EVENTS",
        severity=severity,
        message=f"Completion has {dropped} dropped events." + (
            "" if has_closeout else " Output lacks a clear closeout marker."
        ),
        evidence={
            "dropped-events": dropped,
            "has-closeout": has_closeout,
        },
    )

def _check_high_event_low_output(record: Mapping[str, Any]) -> TerminalQualitySignal | None:
    total_events = _safe_total_events(record)
    output = _safe_output(record)
    if total_events <= _HIGH_EVENT_THRESHOLD or len(output) >= _LOW_OUTPUT_THRESHOLD_CHARS:
        return None
    return TerminalQualitySignal(
        code="TQ-HIGH-EVENT-LOW-OUTPUT",
        severity="critical",
        message=f"High event count ({total_events}) with low output length ({len(output)} chars).",
        evidence={
            "total-events": total_events,
            "output-length": len(output),
        },
    )

def _check_stop_reason(record: Mapping[str, Any]) -> TerminalQualitySignal | None:
    stop_reason = _safe_stop_reason(record)
    if stop_reason == "end_turn" or stop_reason is None:
        return None
    state = record.get("state")
    severity = "warning"
    if state in {"completed"} and stop_reason != "end_turn":
        # Completed but not via normal end — suspicious
        severity = "critical" if stop_reason in {"error", "cancelled"} else "warning"
    elif state == "error":
        severity = "info"  # already error, this is expected context
    return TerminalQualitySignal(
        code="TQ-STOP-REASON",
        severity=severity,
        message=f"Stop reason is '{stop_reason}' (not 'end_turn').",
        evidence={
            "stop-reason": stop_reason,
            "state": state,
        },
    )

def _check_tool_after_last_text(
    record: Mapping[str, Any],
    session_event_summary: Mapping[str, Any] | None,
) -> TerminalQualitySignal | None:
    if session_event_summary is None:
        return None
    last_asst_seq = session_event_summary.get("last-assistant-event-sequence")
    last_tool_seq = session_event_summary.get("last-tool-event-sequence")
    if last_asst_seq is None or last_tool_seq is None:
        return None
    try:
        if int(last_tool_seq) > int(last_asst_seq):
            return TerminalQualitySignal(
                code="TQ-TOOL-AFTER-LAST-TEXT",
                severity="warning",
                message="Last tool event occurred after last assistant text event.",
                evidence={
                    "last-assistant-event-sequence": last_asst_seq,
                    "last-tool-event-sequence": last_tool_seq,
                },
            )
    except (TypeError, ValueError):
        pass
    return None

# ---------------------------------------------------------------------------
# Label aggregation
# ---------------------------------------------------------------------------

_LABEL_SEVERITY_ORDER = {
    TerminalQualityLabel.PREMATURE_HALT_SUSPECTED: 4,
    TerminalQualityLabel.CONTENT_CAPTURE_SUSPECTED: 3,
    TerminalQualityLabel.REPETITION_SUSPECTED: 2,
    TerminalQualityLabel.SUSPICIOUS: 1,
    TerminalQualityLabel.CLEAN: 0,
    TerminalQualityLabel.UNKNOWN: -1,
}

_SIGNAL_TO_LABEL = {
    "TQ-NO-OUTPUT": TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
    "TQ-ENDS-WITH-PREAMBLE": TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
    "TQ-MISSING-EXPECTED-CLOSEOUT": TerminalQualityLabel.SUSPICIOUS,
    "TQ-UNTERMINATED-MARKDOWN": TerminalQualityLabel.SUSPICIOUS,
    "TQ-REPETITION": TerminalQualityLabel.REPETITION_SUSPECTED,
    "TQ-DROPPED-EVENTS": TerminalQualityLabel.CONTENT_CAPTURE_SUSPECTED,
    "TQ-HIGH-EVENT-LOW-OUTPUT": TerminalQualityLabel.PREMATURE_HALT_SUSPECTED,
    "TQ-STOP-REASON": TerminalQualityLabel.SUSPICIOUS,
    "TQ-TOOL-AFTER-LAST-TEXT": TerminalQualityLabel.SUSPICIOUS,
}

def _aggregate_label(signals: list[TerminalQualitySignal]) -> TerminalQualityLabel:
    if not signals:
        return TerminalQualityLabel.CLEAN
    best = TerminalQualityLabel.UNKNOWN
    for sig in signals:
        candidate = _SIGNAL_TO_LABEL.get(sig.code, TerminalQualityLabel.SUSPICIOUS)
        if _LABEL_SEVERITY_ORDER.get(candidate, 0) > _LABEL_SEVERITY_ORDER.get(best, -1):
            best = candidate
    return best

def _compute_confidence(signals: list[TerminalQualitySignal]) -> float:
    """Deterministic confidence: more signals → higher confidence (capped at 1.0)."""
    if not signals:
        return 1.0  # clean is certain when no signals fire
    severity_scores = {
        "critical": 0.5,
        "warning": 0.3,
        "info": 0.1,
    }
    total = sum(severity_scores.get(s.severity, 0.1) for s in signals)
    return min(total, 1.0)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_terminal_output(
    *,
    record: Mapping[str, Any],
    latest_turn: Mapping[str, Any] | None = None,
    session_event_summary: Mapping[str, Any] | None = None,
) -> TerminalQualityReport:
    """Classify the terminal output quality of a request.

    Pure and deterministic — does not import provider adapters, event bus
    internals, or planning code. Does not read raw prompt/tool payloads.

    Args:
        record: Public request record fields (state, output, completion, etc.).
        latest_turn: Redacted latest turn projection (optional).
        session_event_summary: Bounded session event summary with sequence
            numbers and event kinds (optional).

    Returns:
        TerminalQualityReport with label, confidence, signals, and version.
    """
    state = record.get("state")
    if not _is_terminal_state(state):
        # Non-terminal requests are out of scope; return UNKNOWN
        return TerminalQualityReport(
            label=TerminalQualityLabel.UNKNOWN,
            confidence=0.0,
            signals=(),
            classifier_version=CLASSIFIER_VERSION,
        )

    signals: list[TerminalQualitySignal] = []

    # Run all signal checks
    for check_fn in [
        _check_no_output,
        _check_ends_with_preamble,
        _check_missing_closeout,
        _check_unterminated_markdown,
        _check_repetition,
        _check_dropped_events,
        _check_high_event_low_output,
        _check_stop_reason,
    ]:
        sig = check_fn(record)
        if sig is not None:
            signals.append(sig)

    # Session-event-summary-dependent checks (optional input)
    tool_sig = _check_tool_after_last_text(record, session_event_summary)
    if tool_sig is not None:
        signals.append(tool_sig)

    label = _aggregate_label(signals)
    confidence = _compute_confidence(signals)

    return TerminalQualityReport(
        label=label,
        confidence=round(confidence, 2),
        signals=tuple(signals),
        classifier_version=CLASSIFIER_VERSION,
    )
