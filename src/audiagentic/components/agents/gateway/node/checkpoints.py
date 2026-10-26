"""Bounded central receipt custody, serialized by the managed-service owner.

One runtime stream owner per node calls accept, sends its returned ACK outside
ALL locks, then accepts the next receipt. No batch, network callback, provider
call, new queue, or receipt history is introduced here. Canonical receipt writes
must go through this owner: its C+1 gate is what makes latest-exact canonical
replay sufficient after a crash between canonical and sidecar writes.
"""
from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from audiagentic.components.agents.gateway import store as request_store
from audiagentic.foundation.io import atomic_write_json, read_json_with_retry
from audiagentic.foundation.system.managed_service import ManagedServiceStore

from .contracts import CommandIdentity, _identifier, _integer, conflict, invalid
from .receipts import Receipt, _digest, _log_id


@dataclass(frozen=True)
class CanonicalReceiptTarget:
    """Trusted runtime resolution of the ORIGINAL request and current CAS.

    Never populate this from a node payload. The resolver may read local
    canonical state only; it cannot claim receipt acceptance or do network I/O.
    """
    project_root: Path
    owner_epoch: str
    worker_id: str
    attempt_epoch: int
    expected_revision: int

    def __post_init__(self):
        if not isinstance(self.project_root, Path) or not self.project_root.is_absolute():
            raise invalid(1, "Receipt target requires a trusted absolute project root")
        _identifier(self.owner_epoch)
        _identifier(self.worker_id)
        _integer(self.attempt_epoch)
        _integer(self.expected_revision, 0)


@dataclass(frozen=True)
class ReceiptAcknowledgement:
    """Cumulative custody metadata, NEVER effect authorization or a sent ACK."""
    server_id: str
    node_id: str
    log_incarnation_id: str
    sequence: int
    receipt_sha256: str
    gateway_owner_epoch: str

    def payload(self, *, connection_generation: int) -> dict:
        """Owner wraps this in its authenticated live reconcile-result frame."""
        _integer(connection_generation)
        return {
            "kind": "receipt-ack", "server-id": self.server_id,
            "log-incarnation-id": self.log_incarnation_id,
            "connection-generation": connection_generation,
            "through-sequence": self.sequence, "through-receipt-sha256": self.receipt_sha256,
        }


class NodeReceiptCheckpoints:
    """One local stream owner; the existing service guard is its ONLY lock."""

    def __init__(self, service_store: ManagedServiceStore, *, server_id: str, node_id: str):
        self.service_store = service_store
        self.server_id = _identifier(server_id)
        self.node_id = _identifier(node_id)
        # Configuration permits Windows device names (con/nul). No raw node ID
        # is ever used as a path segment, and no new config restriction is added.
        filename = "node-" + hashlib.sha256(node_id.encode("utf-8")).hexdigest() + ".json"
        self.path = service_store.root / "node-receipt-checkpoints" / filename
        self._poisoned = False

    def _read(self) -> dict | None:
        try:
            value = read_json_with_retry(self.path)
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            raise conflict(1, "Central receipt checkpoint is unreadable") from None
        required = {
            "version", "server-id", "node-id", "log-incarnation-id", "sequence",
            "receipt-sha256", "gateway-owner-epoch",
        }
        if not isinstance(value, dict) or set(value) != required or type(value["version"]) is not int or value["version"] != 1:
            raise conflict(1, "Central receipt checkpoint fields are invalid")
        _identifier(value["server-id"])
        _identifier(value["node-id"])
        _identifier(value["gateway-owner-epoch"])
        _log_id(value["log-incarnation-id"])
        _integer(value["sequence"])
        _digest(value["receipt-sha256"])
        if value["server-id"] != self.server_id or value["node-id"] != self.node_id:
            raise conflict(1, "Central receipt checkpoint targets another server or node")
        # gateway-owner-epoch is historical audit data, not current authority.
        return value

    def accept(
        self, receipt: Receipt, *, log_incarnation_id: str, expected_epoch: str,
        resolve_target: Callable[[CommandIdentity], CanonicalReceiptTarget],
    ) -> ReceiptAcknowledgement:
        """Apply C+1 canonically, commit custody, return ACK after releasing locks.

        resolve_target supplies typed ORIGINAL request placement/current CAS
        only. This method itself invokes the fixed canonical receipt mutator;
        a boolean/generic success callback cannot advance custody.

        Exact latest duplicates require the same digest. Older duplicates
        yield only the CURRENT cumulative ACK; no historical receipt is
        revalidated or applied. Unknown log incarnation never resets custody.
        Any cursor write error poisons this instance: close its stream and
        reconstruct from durable state before accepting any further receipt.
        """
        if type(receipt) is not Receipt or type(receipt.identity) is not CommandIdentity:
            raise invalid(1, "Central custody requires a typed node receipt")
        _log_id(log_incarnation_id)
        _integer(receipt.sequence)
        if receipt.identity.node_id != self.node_id:
            raise conflict(1, "Receipt targets another node")
        if receipt.state not in {"prepared", "effect-intent", "native-accepted", "terminal"}:
            raise invalid(1, "Invalid receipt stage")
        if receipt.state == "terminal":
            _digest(receipt.output_sha256)
        elif receipt.output_sha256 is not None:
            raise invalid(1, "Nonterminal receipt cannot contain an output digest")
        digest = receipt.digest

        with self.service_store.owner_guard(expected_epoch):
            if self._poisoned:
                raise conflict(1, "Receipt custody is uncertain; restart the stream owner")
            cursor = self._read()
            if cursor is not None and cursor["log-incarnation-id"] != log_incarnation_id:
                raise conflict(1, "Unknown receipt log incarnation; custody cannot reset")
            sequence = cursor["sequence"] if cursor is not None else 0
            if receipt.sequence <= sequence:
                if receipt.sequence == sequence and digest != cursor["receipt-sha256"]:
                    raise conflict(1, "Latest receipt replay digest changed")
                committed = cursor
            else:
                if receipt.sequence != sequence + 1:
                    raise conflict(1, "Receipt stream has a gap; expected the next sequence")
                target = resolve_target(receipt.identity)
                if type(target) is not CanonicalReceiptTarget:
                    raise invalid(1, "Receipt resolver must return trusted canonical placement and fences")
                # The canonical request lock validates full identity, current
                # worker/attempt/revision, and latest exact replay. A newer
                # canonical receipt conflicts; no inferred recovery is allowed.
                request_store.apply_owned_node_receipt(
                    target.project_root, receipt.identity.request_id,
                    receipt=receipt.public_payload(), owner_epoch=target.owner_epoch,
                    worker_id=target.worker_id, attempt_epoch=target.attempt_epoch,
                    expected_revision=target.expected_revision,
                )
                committed = {
                    "version": 1, "server-id": self.server_id, "node-id": self.node_id,
                    "log-incarnation-id": log_incarnation_id, "sequence": receipt.sequence,
                    "receipt-sha256": digest, "gateway-owner-epoch": expected_epoch,
                }
                try:
                    atomic_write_json(self.path, committed)
                except BaseException:
                    self._poisoned = True
                    raise
            acknowledgement = ReceiptAcknowledgement(
                self.server_id, self.node_id, log_incarnation_id,
                committed["sequence"], committed["receipt-sha256"], expected_epoch,
            )
        # ACK transport belongs to the caller, after every local lock is gone.
        return acknowledgement
