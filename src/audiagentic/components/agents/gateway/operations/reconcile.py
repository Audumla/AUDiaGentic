"""Read-only first reconcile executor (SH24 Slice D)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from audiagentic.components.agents.gateway.store import TERMINAL_STATES
from audiagentic.foundation.contracts.errors import AudiaGenticError

from .contracts import WorkEvidence
from .evidence import GatewayWorkEvidenceReader


class GatewayRequestReader(Protocol):
    """Narrow public request read required for reconcile."""

    def list_execution_requests(self, project_root: Path, **kwargs: Any) -> list[dict[str, Any]]:
        """Return the durable request projection for one project."""
        ...


class GatewayReconcileExecutor:
    """Conservative reconcile that changes nothing without positive evidence."""

    def __init__(self, requests: GatewayRequestReader, evidence: GatewayWorkEvidenceReader | None = None) -> None:
        self._requests = requests
        self._evidence = evidence or GatewayWorkEvidenceReader()

    def execute(self, operation: Mapping[str, Any]) -> Mapping[str, Any]:
        scope = operation.get("scope")
        if not isinstance(scope, Mapping):
            raise AudiaGenticError("VAL-AGM-008", "agents", "gateway operation scope is invalid", {})
        raw_root = scope.get("project-root")
        if not isinstance(raw_root, str) or not raw_root:
            raise AudiaGenticError(
                "VAL-AGM-008", "agents", "reconcile requires a project-root scope", {}
            )
        root = Path(raw_root)
        if not root.is_absolute():
            raise AudiaGenticError(
                "VAL-AGM-008", "agents", "reconcile project-root must be absolute", {}
            )
        records = self._requests.list_execution_requests(root)
        unchanged = 0
        blocked = 0
        unknown = 0
        live = 0
        for record in records:
            if record.get("state") in TERMINAL_STATES:
                unchanged += 1
                continue
            finding = self._evidence.assess(record)
            # The only current nonterminal finding is UNKNOWN.  This explicit
            # branch is the safety boundary: no age/timeout/silence heuristic
            # is permitted to mutate a request here.
            if finding is None or finding.evidence is WorkEvidence.UNKNOWN:
                blocked += 1
                unknown += 1
                continue
            if finding.evidence is WorkEvidence.LIVE:
                # LIVE is a known non-destructive disposition, not an
                # evidence failure and never a reason to retain as UNKNOWN.
                unchanged += 1
                live += 1
                continue
            raise AssertionError("positive-death effects require a later owning transition adapter")
        return {
            "changed": 0,
            "unchanged": unchanged,
            "blocked": blocked,
            "unknown-evidence": unknown,
            "live": live,
        }


__all__ = ["GatewayReconcileExecutor", "GatewayRequestReader"]
