"""Execution-local prompt/profile facts without admission or native effects."""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from audiagentic.components.agents.gateway.admission.instructions import ExpandedPrompt
from audiagentic.components.agents.gateway.admission.semantics import AgentSemantics
from audiagentic.components.agents.gateway.profiles import ResolvedExecutionProfile
from audiagentic.components.agents.models.prompt_definition import PromptDefinition
from audiagentic.foundation.contracts.errors import AudiaGenticError


@dataclass(frozen=True, slots=True)
class LocalPromptMaterialization:
    text: str = field(repr=False)
    template_name: str
    template_sha256: str
    prompt_profile_id: str
    composition_fingerprint: str | None
    prompt_definition_fingerprint: str | None
    expanded: ExpandedPrompt | None = field(repr=False)


def materialize_local_prompt(
    *,
    raw_prompt: str | None,
    semantics: AgentSemantics | None,
    template_context: Mapping[str, Any],
) -> LocalPromptMaterialization:
    """Expand once, retain those bytes, then render with the caller body last."""
    from audiagentic.components.agents.gateway.admission.instructions import (
        expand_agent_prompt,
        render_expanded_prompt,
    )

    text = cast(str, raw_prompt)
    expanded = None
    prompt_profile_id = "default"
    composition_fingerprint = None
    prompt_definition_fingerprint = None
    if semantics is not None:
        prompt_profile_id = semantics.prompt_profile_id
        composition_fingerprint = semantics.composition_fingerprint
        prompt_definition_fingerprint = semantics.prompt_definition_fingerprint
        expanded = expand_agent_prompt(
            semantics.composition.prompt,
            # Repository reads normalize the document's legacy union to typed prompts.
            prompts=cast(tuple[PromptDefinition, ...], semantics.catalog.document.prompts),
            config_root=semantics.config_root,
        )
        text = render_expanded_prompt(expanded, template_context={**template_context, "prompt-body": raw_prompt})
    return LocalPromptMaterialization(
        text=text, template_name=f"prompt-definition:{prompt_profile_id}",
        template_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        prompt_profile_id=prompt_profile_id, composition_fingerprint=composition_fingerprint,
        prompt_definition_fingerprint=prompt_definition_fingerprint, expanded=expanded,
    )


@dataclass(frozen=True, slots=True)
class LocalProfileSelection:
    profile: dict[str, Any]
    snapshot: ResolvedExecutionProfile
    gateway_snapshot: ResolvedExecutionProfile | None


def resolve_local_profile(
    project_root: Path,
    execution_profile_id: str | None,
    *,
    allow_test_fallback: bool,
    profile_resolver: Callable[[Path, str | None], dict[str, Any]] | None = None,
) -> LocalProfileSelection:
    """Preserve both global reads and the existing registry/surface resolver.

    Ordinary admission can retain its existing first-read injection seam;
    independent local callers use the same global catalog owner by default.
    """
    from audiagentic.components.agents.configuration.global_catalog import (
        resolve_global_default_execution_profile,
        resolve_global_execution_profile,
    )
    from audiagentic.components.agents.gateway import profiles

    if profile_resolver is not None:
        profile = profile_resolver(project_root, execution_profile_id)
    else:
        profile = (
            resolve_global_execution_profile(project_root, execution_profile_id)
            if execution_profile_id else resolve_global_default_execution_profile(project_root)
        )
    snapshot = profiles.resolve_for_admission(
        project_root, execution_profile_id, allow_test_fallback=allow_test_fallback,
    )
    gateway_snapshot = snapshot if profiles.get_gateway_registry() is not None else None
    return LocalProfileSelection(profile, snapshot, gateway_snapshot)


@dataclass(frozen=True, slots=True)
class LocalExecutionFacts:
    model_id: str | None
    isolation_tier: str
    runtime_digest: str


def resolve_local_execution_facts(
    *,
    project_root: Path,
    selection: LocalProfileSelection,
    component_profile: str | None,
    prompt: LocalPromptMaterialization,
    provider_chat_url: str | None,
    isolation_resolver: Callable[[str], str] | None = None,
) -> LocalExecutionFacts:
    """Read local model/provider facts in the ordinary admission error order.

    The optional isolation callable preserves ordinary API injection; the
    default always delegates to the public Providers owner.
    """
    from audiagentic.components.agents.contracts.execution_context import (
        compute_agent_runtime_digest,
    )
    from audiagentic.components.agents.gateway.instances import resolve_instance_facts
    from audiagentic.components.providers.providers_api import (
        get_provider_execution_isolation_tier,
        get_provider_runtime_config_state,
    )

    snapshot = selection.snapshot
    model_id = None
    if len(snapshot.instances) == 1:
        model_id = resolve_instance_facts(project_root, tuple(snapshot.instances))[0].model_id
    isolation_tier = (isolation_resolver or get_provider_execution_isolation_tier)(snapshot.provider_id)
    provider_config = get_provider_runtime_config_state(project_root, snapshot.provider_id)
    if provider_chat_url is not None and not snapshot.provider_id.startswith("gpt-auto"):
        raise AudiaGenticError(
            code="VAL-AGW-151", kind="agents",
            message="provider_chat_url is supported only by gpt-auto execution profiles",
            details={"provider-id": snapshot.provider_id},
        )
    runtime_digest = compute_agent_runtime_digest(
        resolved_profile=selection.profile, provider_config_state=provider_config,
        component_overlay={
            "component-profile": component_profile or "",
            "prompt-profile-id": prompt.prompt_profile_id,
            "prompt-template-name": prompt.template_name,
            "prompt-template-digest": prompt.template_sha256,
        },
    )
    return LocalExecutionFacts(model_id, isolation_tier, runtime_digest)


__all__ = [
    "LocalPromptMaterialization", "LocalProfileSelection", "LocalExecutionFacts",
    "materialize_local_prompt", "resolve_local_profile", "resolve_local_execution_facts",
]
