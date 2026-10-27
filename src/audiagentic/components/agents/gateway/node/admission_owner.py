"""Canonical caller-node admission coordinator; no provider or foreign path I/O.

The composition root supplies the existing configured queue and node runner.
This module does not enable native execution, create another scheduler, or
reinterpret connector claims as authorization. Queue drain happens only after
the managed owner, grant and canonical admission locks have been released.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import gateway_node_admission_path
from audiagentic.components.agents.contracts.execution_context import (
    SubmissionEnvelope,
    compute_prompt_digest,
    derive_idempotency_key,
    sanitize_submission_metadata,
)
from audiagentic.components.agents.gateway import profiles, store
from audiagentic.components.agents.gateway.admission.instructions import expand_agent_prompt
from audiagentic.components.agents.gateway.admission.semantics import resolve_agent_semantics
from audiagentic.components.agents.gateway.queue.capacity_policy import (
    resolve_capacity_limits,
    resolve_pending_capacity,
)
from audiagentic.components.agents.gateway.queue.queue import NodeQueuePolicy
from audiagentic.components.agents.gateway.session import sessions_store
from audiagentic.components.agents.models.execution_profile import execution_profile_to_dict
from audiagentic.foundation.io import atomic_write_bytes

from .admission_contract import NodeAdmissionDescriptor, NodeAdmissionPolicy, NodeSubmissionContext
from .contracts import canonical_json, conflict, invalid
from .preparation import PromptSemanticIdentity

_FIELDS = {"agent_id", "execution_profile_id", "prompt_body", "mode", "source", "metadata",
           "session_id", "session_keep_alive", "new_session", "title", "logical_client_id"}


def _read_snapshot(root: Path, record: dict[str, Any]) -> bytes:
    """Read against canonical authority, including on an idempotent replay."""
    descriptor = NodeAdmissionDescriptor.from_mapping(record["node-admission"])
    try:
        raw = gateway_node_admission_path(root, record["request-id"]).read_bytes()
    except OSError:
        raise conflict(1, "Node admission snapshot is unavailable; reconcile without resubmitting") from None
    if hashlib.sha256(raw).hexdigest() != descriptor.snapshot_sha256:
        raise conflict(1, "Node admission snapshot does not match canonical authority")
    return raw


class NodeAdmissionOwner:
    """Service-composed admission owner over existing authorities and stores."""

    def __init__(self, config, authority, service_store, queue, runner):
        self._config = config
        self._authority = authority
        self._service_store = service_store
        self._queue = queue
        self._runner = runner

    def submit(self, project_root: Path, *, context: NodeSubmissionContext,
               arguments: dict[str, Any], owner_epoch: str) -> dict[str, Any]:
        if self._runner is None or type(context) is not NodeSubmissionContext:
            raise invalid(1, "Node admission requires an enabled runner and private ingress context")
        configured = self._config.projects.get(context.server_project_id)
        if (context.server_id != self._config.server_id or configured is None
                or project_root != configured.resolve()
                or self._authority.service_root != self._service_store.root.resolve()):
            raise conflict(1, "Node admission does not match its configured server project owner")
        if not isinstance(arguments, dict) or arguments.keys() - _FIELDS:
            raise invalid(1, "Node submission contains unsupported parameters")
        agent_id = arguments.get("agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise invalid(1, "Node submission requires an agent definition")
        if (arguments.get("session_id") is not None
                or (arguments.get("session_keep_alive") is not None and arguments.get("session_keep_alive") is not False)
                or arguments.get("mode", "async") != "async"
                or type(arguments.get("new_session", False)) is not bool):
            raise invalid(1, "Owned node admission does not support session continuation or blocking mode")
        for name, limit in (("title", 120), ("logical_client_id", 200)):
            value = arguments.get(name)
            if value is not None and (not isinstance(value, str) or not value.strip()
                                      or len(value) > limit or any(ord(c) < 32 for c in value)):
                raise invalid(1, "Node submission title or client identity is invalid")
        metadata = arguments.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise invalid(1, "Node submission metadata must be an object")
        metadata = dict(metadata or {})
        envelope = SubmissionEnvelope.from_mapping({
            "project_root": context.caller_root, "prompt_body": arguments.get("prompt_body"),
            "execution_profile_id": arguments.get("execution_profile_id"),
            "mode": arguments.get("mode", "async"), "source": arguments.get("source"),
            "metadata": metadata, "idempotency_key": metadata.get("idempotency_key"),
            "correlation_id": metadata.get("correlation_id"),
        })
        envelope.validate_fields()  # Never resolve the caller's path on this machine.

        def authorized(callback):
            return self._authority.authorize_admission(
                principal_id=context.principal_id, server_project_id=context.server_project_id,
                node_id=context.node_id, workspace_id=context.workspace_id,
                source_workspace=context.source_workspace, source_node_token=context.source_node_token,
                callback=callback,
            )

        with self._service_store.owner_guard(owner_epoch):
            authorized(lambda placement: placement)  # No semantic I/O for an invalid source credential.

        selected = resolve_agent_semantics(agent_id)
        if envelope.execution_profile_id not in (None, selected.execution_profile_id):
            raise conflict(1, "Node execution profile contradicts its agent definition")
        registry = profiles.get_gateway_registry()
        if registry is None:
            raise conflict(1, "Node admission requires the installed gateway profile registry")
        snapshot = registry.resolve_snapshot(selected.execution_profile_id)
        declared = execution_profile_to_dict(selected.composition.execution_profile)
        comparison = profiles.snapshot_from_resolved_profile(
            declared["profile_id"], declared["provider_id"], tuple(declared["instances"]), declared["params"])
        if (snapshot.provider_id != comparison.provider_id or snapshot.instances != comparison.instances
                or snapshot.config_digest != comparison.config_digest):
            raise conflict(1, "Node agent selection and gateway profile snapshot differ")
        expanded = expand_agent_prompt(selected.composition.prompt,
            prompts=selected.catalog.document.prompts, config_root=selected.config_root)
        semantic = PromptSemanticIdentity(selected.composition_fingerprint, selected.prompt_definition_fingerprint,
            selected.prompt_profile_id, selected.execution_profile_id, expanded.version,
            expanded.sha256, compute_prompt_digest(envelope.prompt_body))
        limits = resolve_capacity_limits(dict(snapshot.execution_params))
        policy = NodeAdmissionPolicy(snapshot.profile_id, snapshot.generation, snapshot.config_digest,
            resolve_pending_capacity(dict(snapshot.execution_params), limits["global"]),
            limits["global"], limits["project"])
        safe_metadata = sanitize_submission_metadata(metadata)
        if arguments.get("title") is not None:
            safe_metadata["caller-title"] = arguments["title"]
        private = canonical_json({
            "contract-version": "node-unrendered-v1", "agent-id": agent_id,
            "raw-prompt": envelope.prompt_body, "expanded-prompt": expanded.content,
            "semantic": semantic.to_mapping(), "source-workspace": context.source_workspace.to_mapping(),
            "caller-root": context.caller_root, "source": envelope.source, "metadata": safe_metadata,
            "logical-client-id": arguments.get("logical_client_id"), "profile": snapshot.to_mapping(),
        })
        descriptor = NodeAdmissionDescriptor(1, context.server_id, semantic, policy,
            hashlib.sha256(private).hexdigest(), context.source_workspace)
        request_id = store.generate_request_id(project_root)
        session = sessions_store.build_session_record(created_by_request_id=request_id,
            provider_transport_kind="worker", execution_profile_id=selected.execution_profile_id)

        def admit(placement):
            if placement.server_id != context.server_id or placement.server_project_id != context.server_project_id:
                raise conflict(1, "Current node grant differs from ingress server scope")
            candidate = store.build_record(request_id=request_id, agent_id=agent_id,
                execution_profile_id=selected.execution_profile_id, prompt_profile_id=selected.prompt_profile_id,
                prompt_definition_fingerprint=selected.prompt_definition_fingerprint,
                prompt_body=envelope.prompt_body, source=envelope.source, metadata=safe_metadata,
                prompt_digest=semantic.raw_prompt_sha256, correlation_id=envelope.correlation_id,
                session_id=session["session-id"], provider_transport_kind="worker",
                node_placement=placement.to_record_mapping(), node_admission=descriptor.to_mapping(),
                gateway_profile_id=snapshot.profile_id, gateway_profile_generation=snapshot.generation,
                gateway_profile_config_digest=snapshot.config_digest)

            def before_write():
                path = gateway_node_admission_path(project_root, request_id)
                if path.exists():
                    if path.read_bytes() != private:
                        raise conflict(1, "Existing private node admission snapshot differs")
                else:
                    atomic_write_bytes(path, private)
                if path.read_bytes() != private:
                    raise conflict(1, "Private node admission snapshot readback failed")
                sessions_store.write_session_record(project_root, session)

            record, created = store.admit_record(project_root, candidate,
                idempotency_key=derive_idempotency_key(envelope.idempotency_key,
                    context_fingerprint=semantic.composition_fingerprint,
                    prompt_digest=semantic.raw_prompt_sha256, session_id=None),
                service_root=self._service_store.root, before_write=before_write)
            _read_snapshot(project_root, record)
            return record, created, placement

        with self._service_store.owner_guard(owner_epoch):
            if not registry.validate_snapshot_current(snapshot):
                raise conflict(1, "Gateway profile changed during node admission")
            record, created, placement = authorized(admit)
        if not created:
            return record
        queue_policy = NodeQueuePolicy(policy.profile_id, policy.generation, policy.config_digest,
            policy.pending_capacity, policy.global_capacity, policy.project_capacity)
        return self._queue.enqueue_node(project_root, record, placement=placement, policy=queue_policy,
            runner=self._runner, dispatch_owner_epoch=owner_epoch, dispatch_service_root=self._service_store.root)
