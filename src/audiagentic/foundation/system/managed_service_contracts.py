"""Typed PR06 managed-service records, validation, and serialization."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, cast

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.logging.redaction import find_denylisted_key
from audiagentic.foundation.workflow import TransitionConfig, TransitionEngine

ServiceState = Literal["starting", "running", "draining", "stopping", "stopped", "failed"]
LeaseState = Literal["active", "released", "expired"]
INACTIVE_LEASE_HISTORY_LIMIT = 256
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
validation_error = make_error_factory("VAL", "MSVC", "managed-service")
conflict_error = make_error_factory("CON", "MSVC", "managed-service")

transition_engine = TransitionEngine(TransitionConfig(
    transitions={
        "starting": frozenset({"running", "failed", "stopping"}),
        "running": frozenset({"draining", "failed", "stopping"}),
        "draining": frozenset({"running", "stopping", "failed"}),
        "stopping": frozenset({"stopped", "failed"}),
        "stopped": frozenset({"starting"}),
        "failed": frozenset({"starting", "stopping", "stopped"}),
    },
    terminal_states=frozenset({"stopped"}),
))


def validate_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise validation_error(1, f"invalid managed-service {label}", field=label, value=value)
    return value


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise validation_error(2, "invalid managed-service timestamp", value=value) from exc
    if parsed.tzinfo is None:
        raise validation_error(2, "managed-service timestamp must include timezone", value=value)
    return parsed.astimezone(timezone.utc)


def add_seconds(value: str, seconds: float) -> str:
    return (parse_time(value) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def validate_facts(facts: Mapping[str, Any] | None, label: str) -> dict[str, Any]:
    result = dict(facts or {})
    denied = find_denylisted_key(result)
    if denied is not None:
        raise validation_error(3, f"{label} contains denylisted field", field=denied)
    try:
        json.dumps(result)
    except (TypeError, ValueError) as exc:
        raise validation_error(4, f"{label} must be JSON serializable") from exc
    return result


@dataclass(frozen=True)
class ServiceKey:
    service_kind: str
    service_id: str
    scope: str = "machine"

    def __post_init__(self) -> None:
        validate_id(self.service_kind, "service-kind")
        validate_id(self.service_id, "service-id")
        validate_id(self.scope, "scope")
        if self.scope != "machine":
            raise validation_error(1, "managed-service v1 supports only machine scope", scope=self.scope)


@dataclass(frozen=True)
class ProcessEvidence:
    pid: int
    scope: str
    command_fingerprint: str
    ownership_proof_kind: str
    owner_epoch: str
    creation_identity: str | None = None
    cwd_fingerprint: str | None = None
    group_identity: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.pid, bool) or not isinstance(self.pid, int) or self.pid <= 0:
            raise validation_error(5, "managed process pid must be a positive integer", pid=self.pid)
        validate_id(self.scope, "process-scope")
        validate_id(self.ownership_proof_kind, "ownership-proof-kind")
        if not self.command_fingerprint or not self.owner_epoch:
            raise validation_error(6, "managed process evidence is incomplete")


@dataclass(frozen=True)
class EndpointInfo:
    protocol: str
    address: str
    auth_reference: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.protocol, "endpoint-protocol")
        if not self.address or any(marker in self.address for marker in ("?", "#", "@")):
            raise validation_error(7, "endpoint address must not contain credentials or query data")
        if self.auth_reference is not None:
            validate_id(self.auth_reference, "auth-reference")


@dataclass(frozen=True)
class ClientLease:
    lease_id: str
    client_instance_id: str
    owner_epoch: str
    state: LeaseState
    acquired_at: str
    renewed_at: str
    expires_at: str
    correlation_id: str | None = None
    facts: Mapping[str, Any] | None = None

    @property
    def active(self) -> bool:
        return self.state == "active"


@dataclass(frozen=True)
class ManagedServiceRecord:
    key: ServiceKey
    state: ServiceState
    revision: int
    owner_epoch: str
    created_at: str
    updated_at: str
    protocol_version: str
    process: ProcessEvidence | None = None
    endpoint: EndpointInfo | None = None
    health_facts: Mapping[str, Any] | None = None
    failure: Mapping[str, Any] | None = None
    leases: tuple[ClientLease, ...] = ()

    @property
    def active_lease_count(self) -> int:
        return sum(lease.active for lease in self.leases)


def normalize_lease_history(
    leases: tuple[ClientLease, ...],
    *,
    current_time: str | None = None,
    expire_active: bool = False,
    inactive_limit: int = INACTIVE_LEASE_HISTORY_LIMIT,
) -> tuple[tuple[ClientLease, ...], bool]:
    """Expire leases through one authority and retain bounded inactive history."""
    current = parse_time(current_time) if current_time is not None else None
    normalized: list[ClientLease] = []
    changed = False
    for lease in leases:
        should_expire = lease.active and (
            expire_active or (current is not None and parse_time(lease.expires_at) <= current)
        )
        if should_expire:
            lease = replace(lease, state="expired")
            changed = True
        normalized.append(lease)

    inactive_count = sum(not lease.active for lease in normalized)
    discard = max(0, inactive_count - inactive_limit)
    if discard:
        retained: list[ClientLease] = []
        for lease in normalized:
            if not lease.active and discard:
                discard -= 1
                changed = True
                continue
            retained.append(lease)
        normalized = retained
    return tuple(normalized), changed


def prepare_restart_record(
    record: ManagedServiceRecord,
    *,
    owner_epoch: str,
    protocol_version: str,
    updated_at: str,
) -> ManagedServiceRecord:
    """Return the single canonical starting record for a replacement owner."""
    return replace(
        record,
        state="starting",
        revision=record.revision + 1,
        owner_epoch=owner_epoch,
        updated_at=updated_at,
        protocol_version=protocol_version,
        process=None,
        endpoint=None,
        health_facts=None,
        failure=None,
        leases=normalize_lease_history(record.leases, expire_active=True)[0],
    )


def record_to_dict(record: ManagedServiceRecord) -> dict[str, Any]:
    process = None if record.process is None else {
        "pid": record.process.pid, "scope": record.process.scope,
        "command-fingerprint": record.process.command_fingerprint,
        "ownership-proof-kind": record.process.ownership_proof_kind,
        "owner-epoch": record.process.owner_epoch,
        "creation-identity": record.process.creation_identity,
        "cwd-fingerprint": record.process.cwd_fingerprint,
        "group-identity": record.process.group_identity,
    }
    endpoint = None if record.endpoint is None else {
        "protocol": record.endpoint.protocol, "address": record.endpoint.address,
        "auth-reference": record.endpoint.auth_reference,
    }
    return {
        "contract-version": "v1", "service-kind": record.key.service_kind,
        "service-id": record.key.service_id, "scope": record.key.scope,
        "state": record.state, "revision": record.revision,
        "owner-epoch": record.owner_epoch, "created-at": record.created_at,
        "updated-at": record.updated_at, "protocol-version": record.protocol_version,
        "process": process, "endpoint": endpoint,
        "health-facts": None if record.health_facts is None else dict(record.health_facts),
        "failure": None if record.failure is None else dict(record.failure),
        "leases": [{
            "lease-id": item.lease_id, "client-instance-id": item.client_instance_id,
            "owner-epoch": item.owner_epoch, "state": item.state,
            "acquired-at": item.acquired_at, "renewed-at": item.renewed_at,
            "expires-at": item.expires_at, "correlation-id": item.correlation_id,
            "facts": None if item.facts is None else dict(item.facts),
        } for item in record.leases],
    }


def record_from_dict(data: Mapping[str, Any]) -> ManagedServiceRecord:
    if data.get("contract-version") != "v1":
        raise validation_error(8, "unsupported managed-service contract version", supported=["v1"])
    key = ServiceKey(str(data.get("service-kind", "")), str(data.get("service-id", "")), str(data.get("scope", "")))
    raw_state = str(data.get("state", ""))
    if not transition_engine.is_known_state(raw_state):
        raise validation_error(9, "unknown managed-service state", state=raw_state)
    process_data = data.get("process")
    process = None if process_data is None else ProcessEvidence(
        pid=process_data["pid"], scope=process_data["scope"],
        command_fingerprint=process_data["command-fingerprint"],
        ownership_proof_kind=process_data["ownership-proof-kind"],
        owner_epoch=process_data["owner-epoch"], creation_identity=process_data.get("creation-identity"),
        cwd_fingerprint=process_data.get("cwd-fingerprint"), group_identity=process_data.get("group-identity"),
    )
    endpoint_data = data.get("endpoint")
    endpoint = None if endpoint_data is None else EndpointInfo(
        endpoint_data["protocol"], endpoint_data["address"], endpoint_data.get("auth-reference")
    )
    leases = tuple(ClientLease(
        lease_id=item["lease-id"], client_instance_id=item["client-instance-id"],
        owner_epoch=item["owner-epoch"], state=item["state"], acquired_at=item["acquired-at"],
        renewed_at=item["renewed-at"], expires_at=item["expires-at"],
        correlation_id=item.get("correlation-id"), facts=validate_facts(item.get("facts"), "lease facts"),
    ) for item in data.get("leases", []))
    return ManagedServiceRecord(
        key=key, state=cast(ServiceState, raw_state), revision=int(data["revision"]),
        owner_epoch=str(data["owner-epoch"]), created_at=str(data["created-at"]),
        updated_at=str(data["updated-at"]), protocol_version=str(data["protocol-version"]),
        process=process, endpoint=endpoint,
        health_facts=None if data.get("health-facts") is None else validate_facts(data["health-facts"], "health facts"),
        failure=None if data.get("failure") is None else validate_facts(data["failure"], "failure facts"), leases=leases,
    )
