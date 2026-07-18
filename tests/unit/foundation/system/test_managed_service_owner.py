from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import ProcessIdentity
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import (
    EndpointInfo,
    ProcessEvidence,
    ServiceKey,
)
from audiagentic.foundation.system.managed_service_owner import ManagedServiceOwner


class Processes:
    def __init__(self) -> None:
        self.alive: dict[int, str] = {}
        self.next_pid = 200

    def evidence(self, epoch: str) -> ProcessEvidence:
        self.next_pid += 1
        creation = f"created-{self.next_pid}"
        self.alive[self.next_pid] = creation
        return ProcessEvidence(
            pid=self.next_pid,
            scope="external-adopted",
            command_fingerprint="sha256:owner",
            ownership_proof_kind="creation-identity",
            owner_epoch=epoch,
            creation_identity=creation,
        )

    def observe(self, evidence: ProcessEvidence) -> ProcessIdentity | None:
        creation = self.alive.get(evidence.pid)
        return None if creation is None else ProcessIdentity(evidence.pid, creation_identity=creation)


def _owner(tmp_path: Path):
    processes = Processes()
    store = ManagedServiceStore(ServiceKey("gateway", "manual"), root=tmp_path)
    owner = ManagedServiceOwner(store, observe=processes.observe)
    endpoint = EndpointInfo("local-http", "127.0.0.1:9876", "gateway-auth")
    return owner, store, processes, endpoint


def test_explicit_owner_claim_rejects_second_live_owner(tmp_path: Path) -> None:
    owner, _store, processes, endpoint = _owner(tmp_path)
    claimed = owner.claim(
        protocol_version="v1",
        endpoint=endpoint,
        evidence_factory=processes.evidence,
        health_facts={"ready": True},
    )

    assert claimed.state == "running"
    assert claimed.process is not None
    with pytest.raises(AudiaGenticError, match="CON-MSVC-034"):
        owner.claim(
            protocol_version="v1",
            endpoint=endpoint,
            evidence_factory=processes.evidence,
        )


def test_dead_owner_record_is_recovered_with_new_epoch(tmp_path: Path) -> None:
    owner, _store, processes, endpoint = _owner(tmp_path)
    first = owner.claim(
        protocol_version="v1", endpoint=endpoint, evidence_factory=processes.evidence
    )
    assert first.process is not None
    processes.alive.pop(first.process.pid)

    recovered = owner.claim(
        protocol_version="v1", endpoint=endpoint, evidence_factory=processes.evidence
    )

    assert recovered.owner_epoch != first.owner_epoch
    assert recovered.process is not None
    assert recovered.process.pid != first.process.pid


def test_owner_retire_requires_zero_leases_and_matching_evidence(tmp_path: Path) -> None:
    owner, store, processes, endpoint = _owner(tmp_path)
    claimed = owner.claim(
        protocol_version="v1", endpoint=endpoint, evidence_factory=processes.evidence
    )
    leased, lease = store.acquire_lease(
        "client-a", ttl_seconds=60, expected_epoch=claimed.owner_epoch
    )

    with pytest.raises(AudiaGenticError, match="CON-MSVC-035"):
        owner.retire(expected_epoch=leased.owner_epoch)
    store.release_lease(lease.lease_id, expected_epoch=leased.owner_epoch)

    retired = owner.retire(expected_epoch=leased.owner_epoch)
    assert retired.state == "stopped"
    assert retired.process is None
