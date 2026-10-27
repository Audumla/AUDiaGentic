"""Publish original node terminal text through the canonical response owner.

The caller supplies a currently authenticated node connection, never peer JSON
as process proof. Receipt custody and original prepared evidence are prerequisites.
Publication grants neither a fresh effect nor permission to read the response.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import gateway_final_response_path
from audiagentic.components.agents.gateway import output, store
from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
from audiagentic.components.agents.gateway.store._records import _read_record_locked
from audiagentic.components.agents.gateway.store._shared import _request_lock
from audiagentic.components.agents.gateway.store._transitions import (
    _finalize_worker_session_if_terminal,
)
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.time import now_iso_z

from .authority import NodeConnectionIdentity
from .contracts import CommandIdentity, conflict, invalid
from .receipts import Receipt
from .terminal_output import parse_worker_terminal_output


def publish_owned_node_terminal(
    project_root: Path,
    *,
    identity: CommandIdentity,
    terminal_receipt: Receipt,
    raw_artifact: bytes,
    connection: NodeConnectionIdentity,
    service_store: ManagedServiceStore,
    current_owner_epoch: str,
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Verify original evidence, write exact text, then commit the terminal CAS.

    Lock order is current service owner -> original canonical request. No grant
    lock is acquired: revocation cannot invalidate already accepted output. The
    authenticated ingress still owns per-command transport and client-read checks.
    A terminal lifecycle winner is never silently resurrected or overwritten.
    """
    from .prepared_evidence import read_prepared_evidence

    if (
        type(identity) is not CommandIdentity or type(terminal_receipt) is not Receipt
        or type(connection) is not NodeConnectionIdentity
        or connection.node_id != identity.node_id
        or connection.gateway_owner_epoch != current_owner_epoch
        or service_store.key != GATEWAY_SERVICE_KEY
    ):
        raise invalid(1, "Node publication requires the current authenticated service and node")
    if terminal_receipt.identity != identity or terminal_receipt.state != "terminal":
        raise conflict(1, "Node publication requires the original terminal receipt")
    artifact = parse_worker_terminal_output(
        raw_artifact, expected_identity=identity,
        expected_sha256=terminal_receipt.output_sha256,
    )
    media_type = {
        "text/plain": "text/plain; charset=utf-8",
        "text/markdown": "text/markdown; charset=utf-8",
    }.get(artifact.media_type, artifact.media_type)
    with service_store.owner_guard(current_owner_epoch):
        with _request_lock(project_root, identity.request_id):
            record = _read_record_locked(project_root, identity.request_id)
            dispatch, placement = record.get("node-dispatch"), record.get("node-placement")
            if (
                not isinstance(dispatch, dict) or not isinstance(placement, dict)
                or dispatch.get("identity") != identity.to_mapping()
                or placement.get("node-id") != identity.node_id
                or placement.get("workspace-id") != identity.workspace_id
                or dispatch.get("authorization-state") != "terminal"
                or not dispatch.get("authorization-id")
                or dispatch.get("receipt-stage") != "terminal"
                or dispatch.get("receipt-sequence") != terminal_receipt.sequence
                or dispatch.get("receipt-sha256") != terminal_receipt.digest
                or dispatch.get("output-sha256") != terminal_receipt.output_sha256
            ):
                raise conflict(1, "Node terminal differs from original canonical receipt custody")
            stored_root = record.get("dispatch-service-root")
            if not stored_root or Path(stored_root).resolve() != service_store.root.resolve():
                raise conflict(1, "Node terminal belongs to a different managed service")
            evidence = read_prepared_evidence(project_root, identity, record, require_authorized=True)
            accepted = evidence.attestation
            if (
                artifact.attestation_sha256 != accepted.digest
                or artifact.private_bundle_sha256 != accepted.provider_manifest_sha256
                or artifact.worker_id != accepted.worker_id
                or artifact.attempt_epoch != accepted.attempt_epoch
                or artifact.provider_id != accepted.provider_id
                or artifact.model_id != accepted.model_id
            ):
                raise conflict(1, "Node terminal output differs from original accepted preparation")
            # The worker identity hash is authenticated node-origin evidence,
            # not a centrally reconstructed process proof. Do not mint one here.
            if record["state"] == "completed":
                final = record.get("response-artifact")
                if (
                    not isinstance(final, dict) or final.get("media-type") != media_type
                    or output.read_final_response(project_root, identity.request_id, final) != artifact.text
                ):
                    raise conflict(1, "Completed node response has a different publication winner")
                return record
            if record["state"] != "running":
                raise conflict(1, "Node terminal requires explicit reconciliation of the lifecycle winner")
            if expected_revision is not None and record["revision"] != expected_revision:
                raise conflict(1, "Node publication revision is stale")
            existing_output = gateway_final_response_path(project_root, identity.request_id)
            if existing_output.is_symlink() or (
                existing_output.exists() and existing_output.read_bytes() != artifact.text.encode("utf-8")
            ):
                raise conflict(1, "Node response differs from an existing private publication")
            published = output.persist_final_response(
                project_root, identity.request_id, artifact.text,
                media_type=media_type, lock_held=True,
            )
            if output.read_final_response(project_root, identity.request_id, published) != artifact.text:
                raise conflict(1, "Node response bytes were not durably published")
            updated = store.transition_owned_terminal(
                project_root, identity.request_id, "completed",
                owner_epoch=record["dispatch-owner-epoch"], worker_id=record["worker-id"],
                attempt_epoch=record["attempt-epoch"], expected_revision=record["revision"],
                service_root=service_store.root, _request_lock_held=True,
                updates={
                    "provider-id": artifact.provider_id, "model-id": artifact.model_id,
                    "response-artifact": {key: published[key] for key in (
                        "artifact-id", "request-id", "media-type", "bytes", "sha256",
                    )},
                    "output-preview": published["output-preview"],
                    "output-truncated": published["output-truncated"], "finished-at": now_iso_z(),
                },
            )
    # Session bookkeeping can acquire its own locks. Never perform it under the
    # canonical publication lock, and never give it native process ownership.
    _finalize_worker_session_if_terminal(project_root, updated)
    return updated


__all__ = ["publish_owned_node_terminal"]
