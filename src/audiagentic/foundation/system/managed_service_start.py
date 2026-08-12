"""Atomic start-or-attach coordination for managed services."""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import ProcessIdentity, ownership_matches
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import (
    ManagedServiceRecord,
    conflict_error,
    normalize_lease_history,
    prepare_restart_record,
    validate_facts,
    validate_id,
    validation_error,
)
from audiagentic.foundation.system.managed_service_lifecycle_contracts import (
    ManagedServiceDeclaration,
    ManagedServiceHooks,
    ServiceHandshake,
    StartDisposition,
    StartOrAttachResult,
)


def _validate_handshake(
    record: ManagedServiceRecord, handshake: ServiceHandshake
) -> dict[str, Any]:
    if handshake.owner_epoch != record.owner_epoch:
        raise conflict_error(22, "service handshake owner epoch does not match")
    if handshake.protocol_version != record.protocol_version:
        raise conflict_error(
            23,
            "service protocol version is incompatible",
            expected=record.protocol_version,
            actual=handshake.protocol_version,
        )
    if handshake.endpoint != record.endpoint:
        raise conflict_error(24, "service handshake endpoint identity does not match")
    return validate_facts(handshake.health_facts, "health facts")


class ManagedServiceStarter:
    """Launch exactly one service or attach a lease to its proven owner."""

    def __init__(self, store: ManagedServiceStore, hooks: ManagedServiceHooks) -> None:
        self.store = store
        self.hooks = hooks

    def start_or_attach(
        self,
        declaration: ManagedServiceDeclaration,
        *,
        client_instance_id: str,
        lease_ttl_seconds: float,
        correlation_id: str | None = None,
        lease_facts: Mapping[str, Any] | None = None,
    ) -> StartOrAttachResult:
        if declaration.key != self.store.key:
            raise validation_error(25, "managed-service declaration key does not match store")
        if declaration.readiness_timeout + 1.0 > self.store.lock_timeout:
            raise validation_error(
                37,
                "readiness timeout exceeds the managed-service lock budget",
                readiness_timeout=declaration.readiness_timeout,
                lock_timeout=self.store.lock_timeout,
            )
        validate_id(client_instance_id, "client-instance-id")
        if isinstance(lease_ttl_seconds, bool) or lease_ttl_seconds <= 0:
            raise validation_error(17, "lease ttl must be positive")
        safe_lease_facts = validate_facts(lease_facts, "lease facts")
        with self.store._lock():
            if self.store.record_path.exists():
                record = self.store._read_unlocked()
                # Reconnect is also the lease-expiry cleanup boundary.  Do
                # this under the same startup lock before deciding whether a
                # draining record is still authoritative; otherwise an expired
                # client lease can strand a dead service forever.
                timestamp = self.store._clock()
                leases, changed = normalize_lease_history(
                    record.leases, current_time=timestamp
                )
                if changed:
                    record = self.store._write_unlocked(
                        replace(
                            record,
                            revision=record.revision + 1,
                            updated_at=timestamp,
                            leases=leases,
                        ),
                        "lease.expired",
                    )
                attached = self._try_attach(
                    record,
                    declaration=declaration,
                    client_instance_id=client_instance_id,
                    lease_ttl_seconds=lease_ttl_seconds,
                    correlation_id=correlation_id,
                    lease_facts=safe_lease_facts,
                )
                if attached is not None:
                    return attached
                record = self._prepare_restart(record, declaration)
                disposition: StartDisposition = "recovered"
            else:
                record = self.store._create_unlocked(declaration.protocol_version)
                disposition = "started"
            return self._launch_and_attach(
                record,
                declaration,
                disposition=disposition,
                client_instance_id=client_instance_id,
                lease_ttl_seconds=lease_ttl_seconds,
                correlation_id=correlation_id,
                lease_facts=safe_lease_facts,
            )

    def _try_attach(
        self,
        record: ManagedServiceRecord,
        *,
        declaration: ManagedServiceDeclaration,
        client_instance_id: str,
        lease_ttl_seconds: float,
        correlation_id: str | None,
        lease_facts: Mapping[str, Any],
    ) -> StartOrAttachResult | None:
        if record.state == "draining":
            # A drain with active clients is still authoritative. Once all
            # leases are gone, a missing/unobservable recorded process is a
            # stale host marker and may enter the normal restart path below.
            if record.active_lease_count:
                raise conflict_error(26, "managed service is draining", state=record.state)
            if record.process is not None and self._observe(record.process) is not None:
                raise conflict_error(28, "service process remains live while draining")
            return None
        if record.state == "stopping":
            raise conflict_error(26, "managed service is stopping", state=record.state)
        if record.state in ("stopped", "failed"):
            if record.process is not None and self._observe(record.process) is not None:
                raise conflict_error(27, "live process remains on non-running service record")
            return None
        if record.protocol_version != declaration.protocol_version:
            raise conflict_error(
                23,
                "service protocol version is incompatible",
                expected=declaration.protocol_version,
                actual=record.protocol_version,
            )
        if record.endpoint is not None and record.endpoint != declaration.endpoint:
            raise conflict_error(24, "service endpoint identity is incompatible")
        if record.state not in ("starting", "running") or record.process is None:
            return None
        observed = self._observe(record.process)
        if observed is None:
            return None
        if not ownership_matches(record.process, observed):
            raise conflict_error(28, "service process ownership cannot be proven", pid=record.process.pid)
        handshake = self._wait_ready(record, declaration)
        facts = _validate_handshake(record, handshake)
        if record.state == "starting":
            record = replace(
                record,
                state="running",
                revision=record.revision + 1,
                updated_at=self.store._clock(),
                health_facts=facts,
            )
            record = self.store._write_unlocked(record, "service.recovered")
            disposition: StartDisposition = "recovered"
        else:
            disposition = "attached"
        record, lease = self.store._acquire_lease_unlocked(
            record,
            client_instance_id,
            ttl_seconds=lease_ttl_seconds,
            expected_epoch=record.owner_epoch,
            correlation_id=correlation_id,
            facts=lease_facts,
        )
        return StartOrAttachResult(record, lease, disposition)

    def _prepare_restart(
        self,
        record: ManagedServiceRecord,
        declaration: ManagedServiceDeclaration,
    ) -> ManagedServiceRecord:
        restarted = prepare_restart_record(
            record,
            owner_epoch=uuid.uuid4().hex,
            protocol_version=declaration.protocol_version,
            updated_at=self.store._clock(),
        )
        return self.store._write_unlocked(restarted, "service.restart-requested")

    def _launch_and_attach(
        self,
        record: ManagedServiceRecord,
        declaration: ManagedServiceDeclaration,
        *,
        disposition: StartDisposition,
        client_instance_id: str,
        lease_ttl_seconds: float,
        correlation_id: str | None,
        lease_facts: Mapping[str, Any],
    ) -> StartOrAttachResult:
        process = None
        try:
            process = self.hooks.launch(declaration.process, owner_epoch=record.owner_epoch)
            if process.owner_epoch != record.owner_epoch:
                raise conflict_error(16, "launched process evidence has the wrong owner epoch")
            record = replace(
                record,
                revision=record.revision + 1,
                updated_at=self.store._clock(),
                process=process,
                endpoint=declaration.endpoint,
            )
            record = self.store._write_unlocked(record, "service.process-launched")
            observed = self._observe(process)
            if not ownership_matches(process, observed):
                raise conflict_error(28, "launched process ownership cannot be proven", pid=process.pid)
            handshake = self._wait_ready(record, declaration)
            facts = _validate_handshake(record, handshake)
        except Exception as exc:
            if process is not None:
                try:
                    observed = self._observe(process)
                except AudiaGenticError:
                    observed = None
                if ownership_matches(process, observed):
                    try:
                        self.hooks.signal(process, observed, force=True)
                    except Exception:  # noqa: BLE001 - preserve primary failure
                        pass
            failed = replace(
                record,
                state="failed",
                revision=record.revision + 1,
                updated_at=self.store._clock(),
                failure={"failure-class": "launch-or-readiness"},
            )
            self.store._write_unlocked(failed, "service.start-failed")
            if isinstance(exc, AudiaGenticError):
                raise
            raise conflict_error(33, "managed-service lifecycle hook failed") from exc
        running = replace(
            record,
            state="running",
            revision=record.revision + 1,
            updated_at=self.store._clock(),
            health_facts=facts,
        )
        running = self.store._write_unlocked(running, "service.ready")
        running, lease = self.store._acquire_lease_unlocked(
            running,
            client_instance_id,
            ttl_seconds=lease_ttl_seconds,
            expected_epoch=running.owner_epoch,
            correlation_id=correlation_id,
            facts=lease_facts,
        )
        return StartOrAttachResult(running, lease, disposition)

    def _wait_ready(
        self,
        record: ManagedServiceRecord,
        declaration: ManagedServiceDeclaration,
    ) -> ServiceHandshake:
        timeout = declaration.readiness_timeout
        interval = declaration.readiness_poll_interval
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                handshake = self.hooks.handshake(record)
            except Exception:  # noqa: BLE001 - readiness probing is bounded
                handshake = None
            if handshake is not None and handshake.ready:
                return handshake
            time.sleep(interval)
        raise conflict_error(
            29,
            "managed service did not become ready",
            pid=record.process.pid if record.process else None,
        )

    def _observe(self, process) -> ProcessIdentity | None:
        try:
            return self.hooks.observe(process)
        except AudiaGenticError:
            raise
        except Exception as exc:
            raise conflict_error(33, "managed-service process observation failed") from exc


__all__ = ["ManagedServiceStarter"]
