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
        # Evidence is supplied by a provider-neutral, request-bound observer;
        # timeouts, silence, missing handles and arbitrary recovery metadata
        # are intentionally not interpreted here.
        raw = record.get("reconciliation-evidence")
        if isinstance(raw, Mapping):
            classification = raw.get("classification")
            if classification == "live":
                return EvidenceFinding(WorkEvidence.LIVE, "positive-owner-liveness-evidence")
            if classification == "proven-dead":
                worker_id = raw.get("worker-id")
                attempt_epoch = raw.get("attempt-epoch")
                if (
                    isinstance(worker_id, str)
                    and worker_id
                    and isinstance(attempt_epoch, int)
                    and attempt_epoch > 0
                    and worker_id == record.get("worker-id")
                    and attempt_epoch == record.get("attempt-epoch")
                ):
                    return EvidenceFinding(WorkEvidence.PROVEN_DEAD, "fenced-owner-death-evidence")
                return EvidenceFinding(WorkEvidence.UNKNOWN, "owner-fence-mismatch")
        return EvidenceFinding(
            WorkEvidence.UNKNOWN,
            "no-positive-owner-death-evidence",
        )


__all__ = ["EvidenceFinding", "GatewayWorkEvidenceReader"]
