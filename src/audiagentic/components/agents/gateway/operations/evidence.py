"""Conservative, provider-independent evidence classification for SH24."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from audiagentic.components.agents.gateway.store import TERMINAL_STATES

from .contracts import WorkEvidence


@dataclass(frozen=True)
class EvidenceFinding:
    """A bounded classification, intentionally separate from lifecycle state."""

    evidence: WorkEvidence
    reason: str


class GatewayWorkEvidenceReader:
    """Classify only evidence that is actually present in durable records.

    The initial implementation deliberately has no provider/process observer.
    It therefore cannot claim a nonterminal request is dead.  Later SH22/AS91
    adapters can add positive, request-bound evidence without changing the
    operation workflow or callers.
    """

    def assess(self, record: Mapping[str, Any]) -> EvidenceFinding | None:
        state = record.get("state")
        if state in TERMINAL_STATES:
            return None
        return EvidenceFinding(
            WorkEvidence.UNKNOWN,
            "no-positive-owner-death-evidence",
        )


__all__ = ["EvidenceFinding", "GatewayWorkEvidenceReader"]
