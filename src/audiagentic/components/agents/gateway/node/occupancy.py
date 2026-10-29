"""Read-only node occupancy projected from canonical gateway request records.

Scheduling snapshots are an optimization, never effect authorization. The future
NodeRunner MUST serialize fresh effects in this order: managed-service owner_guard
-> NodeGrantAuthority auth lock -> this projection (excluding its own request)
-> canonical request lock/authorization commit. No queue/manager lock may be held
while acquiring those authority locks. This module takes none of them, performs
no network I/O and owns no durable state. Only configured server project roots
are inspected; wire/native workspace paths are never discovery inputs.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import gateway_root
from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.node.contracts import canonical_json
from audiagentic.foundation.contracts.errors import AudiaGenticError


def record_holds_node(record: dict[str, Any]) -> bool:
    """Outer terminal state cannot settle an authorized/possibly native effect.

    The canonical contract represents definitive completion/stop by a terminal
    native receipt. A terminal, positively never-authorized request is also
    effect-free. Unknown states/evidence retain occupancy; an ACK is only custody.
    """
    dispatch = record.get("node-dispatch")
    terminal = record.get("state") in store.TERMINAL_STATES
    if dispatch is None:
        # Strict protocol cannot authorize a native effect without a bound
        # command. Status/owner fences alone are not unresolved native work.
        # Live preparation is covered by the existing in-process reservation.
        return False
    if not isinstance(dispatch, dict):
        return True
    if not {
        "identity", "authorization-state", "authorization-id", "receipt-stage",
        "receipt-sequence", "receipt-sha256", "output-sha256",
    }.issubset(dispatch):
        return True
    authorization = dispatch.get("authorization-state")
    stage = dispatch.get("receipt-stage")
    if (
        authorization == "terminal" and stage == "terminal"
        and dispatch.get("authorization-id")
        and type(dispatch.get("receipt-sequence")) is int
        and dispatch["receipt-sequence"] > 0
        and dispatch.get("receipt-sha256") and dispatch.get("output-sha256")
    ):
        expected_digest = hashlib.sha256(canonical_json({
            "identity": dispatch["identity"], "state": "terminal",
            "receipt-sequence": dispatch["receipt-sequence"],
            "output-sha256": dispatch["output-sha256"],
        })).hexdigest()
        return dispatch["receipt-sha256"] != expected_digest
    if (
        terminal and authorization == "not-authorized"
        and dispatch.get("authorization-id") is None
        and stage in (None, "prepared")
    ):
        return False
    return True


@dataclass(frozen=True)
class NodeOccupancySnapshot:
    # server, node, trusted central project root, request id
    holders: frozenset[tuple[str, str, Path, str]] = frozenset()
    unproven: bool = False
    # Positive monotonic settlement proof, not absence from a possibly older scan.
    released_requests: frozenset[tuple[Path, str]] = frozenset()

    def occupied(
        self, server_id: str, node_id: str, *, exclude_request: tuple[Path, str] | None = None,
    ) -> bool:
        return self.unproven or any(
            server == server_id and node == node_id
            and (exclude_request is None or (root, request) != exclude_request)
            for server, node, root, request in self.holders
        )


class NodeOccupancy:
    """Pure projection over the complete, owner-configured central root set."""

    def __init__(self, project_roots: tuple[Path, ...], *, server_id: str | None = None):
        if any(not isinstance(root, Path) or not root.is_absolute() for root in project_roots):
            raise ValueError("node occupancy requires trusted absolute server project roots")
        self.project_roots = tuple(dict.fromkeys(root.resolve() for root in project_roots))
        if project_roots and (not isinstance(server_id, str) or not server_id):
            raise ValueError("node occupancy requires the owning configured server identity")
        self.server_id = server_id

    def snapshot(self) -> NodeOccupancySnapshot:
        holders: set[tuple[str, str, Path, str]] = set()
        released: set[tuple[Path, str]] = set()
        unproven = False
        for project_root in self.project_roots:
            try:
                root = gateway_root(project_root)
                if not root.exists():
                    continue
                # list_records intentionally skips unreadable records for UI use.
                # Occupancy must fail closed instead, and must include terminals.
                for entry in root.iterdir():
                    if entry.name in {"idempotency", "sessions"} or not entry.is_dir():
                        continue
                    if entry.is_symlink():
                        unproven = True
                        continue
                    if not (entry / "record.json").is_file():
                        continue
                    record = store.read_record(project_root, entry.name, include_output=False)
                    placement = record.get("node-placement")
                    if placement is None:
                        if record.get("node-dispatch") is not None:
                            unproven = True
                        continue
                    node = placement["node-id"]
                    dispatch = record.get("node-dispatch")
                    if isinstance(dispatch, dict) and (
                        dispatch["identity"]["node-id"] != node
                        or dispatch["identity"]["request-id"] != record["request-id"]
                    ):
                        unproven = True
                        continue
                    if record_holds_node(record):
                        holders.add((self.server_id, node, project_root, record["request-id"]))
                    elif record["state"] in store.TERMINAL_STATES or (
                        isinstance(record.get("node-dispatch"), dict)
                        and record["node-dispatch"].get("receipt-stage") == "terminal"
                    ):
                        released.add((project_root, record["request-id"]))
            except (OSError, ValueError, KeyError, TypeError, AudiaGenticError):
                unproven = True
        return NodeOccupancySnapshot(frozenset(holders), unproven, frozenset(released))
