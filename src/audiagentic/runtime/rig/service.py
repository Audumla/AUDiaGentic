"""Managed-service projection for the shared embedded llama.cpp rig.

The rig is one machine-scoped service.  This module deliberately owns no PID
files, client files, or process scans: foundation's managed-service record and
leases are the sole lifecycle authority.
"""
from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass, field

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_process import (
    DetachedLaunch,
    observe_process,
    signal_owned_process,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import EndpointInfo, ServiceKey
from audiagentic.foundation.system.managed_service_lifecycle import (
    ManagedServiceDeclaration,
    ManagedServiceHooks,
    ManagedServiceLifecycle,
    ServiceHandshake,
)
from audiagentic.runtime.rig.constants import DEFAULT_HOST
from audiagentic.runtime.rig.embedded.launch import prepare_launch
from audiagentic.runtime.rig.embedded.process import build_command
from audiagentic.runtime.rig.http import probe_models_endpoint

RIG_SERVICE_KEY = ServiceKey("embedded-rig", "default")
_LEASE_TTL_SECONDS = 300.0
_PROTOCOL_PREFIX = "llama-cpp-openai-v1"


@dataclass
class RigAttachment:
    """One client lease over the shared embedded-rig service."""

    endpoint: str
    model: str
    lease_id: str
    owner_epoch: str
    _stop_renewal: threading.Event = field(default_factory=threading.Event, repr=False)
    _renewal_thread: threading.Thread | None = field(default=None, repr=False)

    def start_renewal(self) -> None:
        if self._renewal_thread is not None:
            return
        thread = threading.Thread(
            target=self._renew_forever,
            name="embedded-rig-lease-renewal",
            daemon=True,
        )
        self._renewal_thread = thread
        thread.start()

    def _renew_forever(self) -> None:
        store = ManagedServiceStore(RIG_SERVICE_KEY)
        while not self._stop_renewal.wait(_LEASE_TTL_SECONDS / 2):
            try:
                store.renew_lease(
                    self.lease_id,
                    ttl_seconds=_LEASE_TTL_SECONDS,
                    expected_epoch=self.owner_epoch,
                )
            except AudiaGenticError:
                # A replaced/stopped service must not be resurrected by a stale client.
                return


def start_or_attach_embedded_rig(
    *,
    profile_name: str,
    rig_port: int,
    model_id: str,
) -> RigAttachment:
    """Start one compatible rig or attach a renewable client lease.

    A profile is part of the service protocol identity.  A different requested
    profile therefore fails as incompatible while the proven existing process
    remains untouched.
    """
    endpoint = f"http://{DEFAULT_HOST}:{rig_port}/v1"
    endpoint_info = EndpointInfo("openai-compatible", f"{DEFAULT_HOST}:{rig_port}/v1")
    protocol_version = _protocol_version(profile_name)
    plan = prepare_launch(
        model_profile=profile_name,
        server_bin=None,
        model_file=None,
        device=None,
        gpu_layers=None,
        context=None,
        parallel=None,
        fit=None,
        reasoning=None,
    )
    declaration = ManagedServiceDeclaration(
        key=RIG_SERVICE_KEY,
        process=DetachedLaunch(
            tuple(build_command(
                binary=plan.binary,
                model_arg=plan.model_arg,
                host=DEFAULT_HOST,
                port=rig_port,
                device=plan.device,
                server_cfg=plan.server_cfg,
                chat_template_kwargs=plan.profile.chat_template_kwargs,
                alias=plan.profile.name,
            )),
            cwd=plan.server_dir,
        ),
        endpoint=endpoint_info,
        protocol_version=protocol_version,
        readiness_timeout=90.0,
        readiness_poll_interval=0.25,
    )
    store = ManagedServiceStore(RIG_SERVICE_KEY, lock_timeout=95.0)
    lifecycle = ManagedServiceLifecycle(store, _hooks(endpoint, profile_name))
    result = lifecycle.start_or_attach(
        declaration,
        client_instance_id=f"rig-client-{uuid.uuid4().hex[:16]}",
        lease_ttl_seconds=_LEASE_TTL_SECONDS,
        lease_facts={"client": "harness", "profile": profile_name},
    )
    attachment = RigAttachment(
        endpoint=endpoint,
        model=model_id,
        lease_id=result.lease.lease_id,
        owner_epoch=result.record.owner_epoch,
    )
    attachment.start_renewal()
    return attachment


def release_embedded_rig(attachment: RigAttachment) -> None:
    """Release one client lease and stop only a proven, quiescent last owner."""
    attachment._stop_renewal.set()
    store = ManagedServiceStore(RIG_SERVICE_KEY)
    lifecycle = ManagedServiceLifecycle(store, _hooks(attachment.endpoint, None))
    try:
        released = store.release_lease(
            attachment.lease_id, expected_epoch=attachment.owner_epoch
        )
    except AudiaGenticError:
        return
    if released.active_lease_count:
        return
    try:
        draining = lifecycle.request_drain(
            expected_revision=released.revision,
            expected_epoch=released.owner_epoch,
        )
        lifecycle.stop_if_quiescent(expected_epoch=draining.owner_epoch)
    except AudiaGenticError:
        # A concurrent attach/recovery wins safely; it is never a reason to kill.
        return


def _hooks(endpoint: str, expected_profile: str | None) -> ManagedServiceHooks:
    def handshake(record) -> ServiceHandshake:
        probe = probe_models_endpoint(endpoint, timeout=2.0)
        served_model = None if probe is None else probe.first_model_id
        ready = probe is not None and (
            expected_profile is None or served_model == expected_profile
        )
        return ServiceHandshake(
            ready=ready,
            owner_epoch=record.owner_epoch,
            protocol_version=record.protocol_version,
            endpoint=record.endpoint,
            health_facts={"model": served_model, "models-ready": probe is not None},
        )

    def request_stop(record) -> None:
        observed = observe_process(record.process)
        signal_owned_process(record.process, observed, force=False)

    return ManagedServiceHooks(
        handshake=handshake,
        quiescent=lambda _record: True,
        request_stop=request_stop,
    )


def _protocol_version(profile_name: str) -> str:
    digest = hashlib.sha256(profile_name.encode("utf-8")).hexdigest()[:12]
    return f"{_PROTOCOL_PREFIX}-{digest}"


__all__ = [
    "RIG_SERVICE_KEY",
    "RigAttachment",
    "release_embedded_rig",
    "start_or_attach_embedded_rig",
]
