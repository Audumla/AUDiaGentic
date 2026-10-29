"""Read-only, node-local preparation of one isolated worker turn.

This owner neither authorizes nor executes a command. All private bytes remain
in the returned preparation; callers own subsequent receipt/effect fencing.
"""
from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from typing import Any

from audiagentic.components.agents.contracts.execution_context import (
    SessionSpec,
    SubmissionEnvelope,
    build_manifest,
    sanitize_submission_metadata,
)
from audiagentic.components.agents.contracts.worker_protocol import (
    WorkerExecuteEnvelope,
    WorkerExecutionIdentity,
)
from audiagentic.components.agents.gateway.admission import local_dispatch, semantics
from audiagentic.components.agents.gateway.admission.context import (
    ComponentContextReader,
    build_agent_template_context,
    empty_component_context,
)
from audiagentic.components.agents.gateway.admission.packet import build_provider_packet
from audiagentic.components.agents.gateway.node.contracts import (
    _identifier,
    _integer,
    canonical_json,
    conflict,
    invalid,
)
from audiagentic.components.agents.gateway.node.preparation import (
    PreparationBinding,
    PromptSemanticIdentity,
    RetainedNodePreparation,
    prepare_node_command,
)
from audiagentic.components.agents.gateway.service.shared_config import SharedGatewayNodeConfig
from audiagentic.components.agents.models.execution_profile import execution_profile_to_dict
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.paths.names import get_active_profile
from audiagentic.foundation.time import now_iso_z


class NodeLocalPreparer:
    """Resolve configured local facts; never accept an execution root from wire."""

    def __init__(
        self,
        config: SharedGatewayNodeConfig,
        *,
        component_context_reader: ComponentContextReader | None = None,
        component_profile: str | None = None,
    ) -> None:
        self._node_id = config.node_id
        self._workspaces = dict(config.workspaces)
        self._component_reader = component_context_reader or empty_component_context
        self._component_profile = (
            get_active_profile() if component_profile is None else component_profile
        ) or ""

    def prepare(
        self,
        *,
        binding: PreparationBinding,
        semantic: PromptSemanticIdentity,
        agent_id: str,
        raw_prompt: str,
        worker_id: str,
        attempt_epoch: int,
        source: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        mode: str = "async",
        session: SessionSpec | None = None,
        provider_chat_url: str | None = None,
        timeout_seconds: float | None = None,
    ) -> RetainedNodePreparation:
        """Materialize once, verify selected semantics, then resolve local facts.

        Session continuations, named session surfaces, multi-instance scheduling
        and non-isolated transports are deliberately unsupported here. This is
        preparation only, not a substitute for central authorization or a queue.
        """
        if type(binding) is not PreparationBinding or type(semantic) is not PromptSemanticIdentity:
            raise invalid(1, "Local preparation requires typed binding and semantic identity")
        if binding.node_id != self._node_id or binding.workspace_id not in self._workspaces:
            raise conflict(1, "Preparation node or workspace is not configured locally")
        _identifier(agent_id)
        _identifier(worker_id)
        _integer(attempt_epoch)
        if not isinstance(raw_prompt, str):
            raise invalid(1, "Preparation prompt must be text")
        workspace = self._workspaces[binding.workspace_id]
        if semantic.execution_profile_id not in workspace.execution_profiles:
            raise conflict(1, "Preparation execution profile is not allowed in this workspace")
        session = session if session is not None else SessionSpec()
        if (mode != "async" or type(session) is not SessionSpec or session.session_id is not None
                or session.keep_alive not in (None, False)
                or session.idle_timeout_seconds is not None or session.max_lifetime_seconds is not None
                or provider_chat_url is not None):
            raise invalid(1, "Node preparation supports only asynchronous isolated worker turns")
        if not workspace.root.is_absolute():
            raise invalid(1, "Configured node workspace root must be absolute")
        try:
            root = workspace.root.resolve(strict=True)
            if not root.is_dir():
                raise OSError
        except (OSError, RuntimeError):
            raise invalid(1, "Configured node workspace root is unavailable") from None

        template_context = build_agent_template_context(
            root, component_reader=self._component_reader, workspace_name=None, agent_id=agent_id,
        )
        selected = semantics.resolve_agent_semantics(agent_id)
        prompt = local_dispatch.materialize_local_prompt(
            raw_prompt=raw_prompt, semantics=selected, template_context=template_context,
        )
        if prompt.expanded is None:
            raise conflict(1, "Agent preparation requires retained expanded prompt content")
        try:
            raw_sha256 = hashlib.sha256(raw_prompt.encode("utf-8")).hexdigest()
        except UnicodeError:
            raise invalid(1, "Preparation prompt must be valid UTF-8 text") from None
        actual_semantic = PromptSemanticIdentity(
            selected.composition_fingerprint, selected.prompt_definition_fingerprint,
            selected.prompt_profile_id, selected.execution_profile_id,
            prompt.expanded.version, prompt.expanded.sha256, raw_sha256,
        )
        if actual_semantic != semantic:
            raise conflict(1, "Local selected semantics or expanded/raw prompt differs from preparation")
        # Compare the SAME expansion returned by materialization before any
        # provider/profile-local resolution. Never pre-expand then re-read files.
        expected_profile = execution_profile_to_dict(selected.composition.execution_profile)
        if expected_profile.get("surface_id"):
            raise invalid(1, "Node worker preparation does not support provider-session surfaces")
        selection = local_dispatch.resolve_local_profile(
            root, selected.execution_profile_id, allow_test_fallback=False,
        )
        snapshot = selection.snapshot
        if (canonical_json(selection.profile) != canonical_json(expected_profile)
                or snapshot.profile_id != expected_profile["profile_id"]
                or snapshot.provider_id != expected_profile["provider_id"]
                or tuple(snapshot.instances) != tuple(expected_profile["instances"])
                or canonical_json(snapshot.execution_params) != canonical_json(expected_profile["params"])
                or selection.gateway_snapshot is None):
            raise conflict(1, "Installed profile snapshot differs from selected local catalog profile")
        if snapshot.resolved_surface_id is not None or snapshot.resolved_surface_version is not None:
            raise invalid(1, "Node worker preparation does not support resolved session surfaces")
        if len(snapshot.instances) != 1:
            raise invalid(1, "Node preparation requires a single selected model instance")
        facts = local_dispatch.resolve_local_execution_facts(
            project_root=root, selection=selection, component_profile=self._component_profile,
            prompt=prompt, provider_chat_url=None,
        )
        if facts.isolation_tier != "full-isolation":
            raise invalid(1, "Node preparation requires full-isolation worker execution")
        from audiagentic.components.providers import providers_api

        # This narrow preflight is not an atomic snapshot with the frozen
        # runtime digest. The effect owner must revalidate before execution.
        if not providers_api.is_provider_enabled_for_launch(root, snapshot.provider_id):
            raise AudiaGenticError(
                code="VAL-AGW-031", kind="agents",
                message="execution profile references a disabled provider",
                details={"provider-id": snapshot.provider_id},
            )
        model_alias = selection.profile.get("model_alias")
        launch_model = providers_api.resolve_launch_model(
            root, provider_id=snapshot.provider_id, model_id=facts.model_id, model_alias=model_alias,
        )
        if not isinstance(launch_model, Mapping):
            raise invalid(1, "Provider launch model did not resolve a concrete model-id")
        model_id = launch_model.get("model-id")
        if (not isinstance(model_id, str) or not model_id or model_id != model_id.strip()
                or len(model_id) > 512 or any(ord(c) < 32 or ord(c) == 127 for c in model_id)):
            raise invalid(1, "Provider launch model did not resolve a concrete model-id")
        envelope = SubmissionEnvelope(
            project_root=str(root), execution_profile_id=selected.execution_profile_id,
            component_profile=self._component_profile, prompt_body=raw_prompt,
            mode=mode, session=session, timeout_seconds=timeout_seconds, source=source,
            metadata=sanitize_submission_metadata(metadata),
        )
        canonical_root = envelope.validate()
        manifest = build_manifest(
            envelope, manifest_id=f"mf_{uuid.uuid4().hex}", request_id=binding.request_id,
            resolved_at=now_iso_z(), canonical_root=canonical_root,
            execution_profile_id=selected.execution_profile_id, provider_id=snapshot.provider_id,
            model_id=model_id, provider_isolation_tier="full-isolation",
            agent_runtime_digest=facts.runtime_digest,
            agent_config_fingerprint=selected.composition_fingerprint,
        )
        packet = build_provider_packet(
            execution_root=root, request_id=binding.request_id, profile=selection.profile,
            prompt_profile_id=prompt.prompt_profile_id, prompt_template_name=prompt.template_name,
            prompt_template_digest=prompt.template_sha256,
            prompt_definition_fingerprint=prompt.prompt_definition_fingerprint,
            model_id=model_id, dispatch_prompt=prompt.text, source=envelope.source,
            metadata=envelope.metadata, template_context=template_context,
        )
        identity = WorkerExecutionIdentity(
            worker_id=worker_id, attempt_epoch=attempt_epoch, manifest_id=manifest.manifest_id,
            context_fingerprint=manifest.context_fingerprint, project_root=str(root),
            component_profile=self._component_profile, provider_isolation_tier="full-isolation",
        )
        request = providers_api.ProviderExecutionRequest(
            project_root=root, provider_id=snapshot.provider_id, model_id=model_id,
            model_alias=model_alias, packet_data=packet, worker_id=worker_id,
            attempt_epoch=attempt_epoch, provider_isolation_tier="full-isolation",
        )
        # Validate the existing private worker contract without starting a worker.
        WorkerExecuteEnvelope(identity, request.to_mapping())
        private_manifest = canonical_json({
            "version": 1, "kind": "node-worker-preparation",
            "worker-identity": identity.to_mapping(tier_field="provider-isolation-tier"),
            "execution-manifest": manifest.to_mapping(), "provider-request": request.to_mapping(),
        })
        return prepare_node_command(
            binding=binding, semantic=actual_semantic, raw_prompt=raw_prompt,
            rendered_prompt=prompt.text, manifest_id=manifest.manifest_id,
            context_fingerprint=manifest.context_fingerprint, runtime_digest=facts.runtime_digest,
            provider_manifest=private_manifest, worker_id=worker_id, attempt_epoch=attempt_epoch,
            provider_id=snapshot.provider_id, model_id=model_id, model_alias=model_alias,
        )


__all__ = ["NodeLocalPreparer"]
