"""Pure resolution helpers for canonical agent configuration."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiagentic.components.agents.capabilities.contracts import RoleManifest
from audiagentic.components.agents.capabilities.resolver import resolve_role_manifest
from audiagentic.components.agents.capabilities.source_filter import eligible_instance_ids
from audiagentic.components.agents.capabilities.vocabulary import CapabilityVocabulary
from audiagentic.components.agents.models.agent_definition import agent_definition_from_dict
from audiagentic.components.agents.models.execution_profile import execution_profile_from_dict
from audiagentic.components.agents.models.role import role_from_dict

from .contracts import AgentsConfigDocument
from .repository import AgentsConfigRepository, AgentsConfigSnapshot


@dataclass(frozen=True, slots=True)
class AgentConfigIdentity:
    agent_id: str
    config_digest: str
    agent_definition_fingerprint: str
    prompt_id: str
    prompt_definition_fingerprint: str
    system_prompt_digest: str
    role_ids: tuple[str, ...]
    role_set_fingerprint: str
    capability_requirements_fingerprint: str
    execution_profile_id: str
    execution_profile_fingerprint: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ResolvedAgentComposition:
    identity: AgentConfigIdentity
    roles: tuple[Any, ...]
    execution_profile: Any
    prompt: Any


@dataclass(frozen=True, slots=True)
class AgentAdmission:
    identity: AgentConfigIdentity
    role_manifest: RoleManifest
    eligible_instance_ids: tuple[str, ...]
    prompt: Any
    execution_profile: Any


def resolve_agent(document: AgentsConfigDocument, agent_id: str) -> dict[str, Any]:
    """Resolve one agent and references without disk, providers, or clocks."""
    agent = next((item for item in document.agents if item.get("agent_id") == agent_id), None)
    if agent is None:
        raise KeyError(agent_id)
    role_ids = agent.get("role_ids", agent.get("role-ids"))
    if role_ids is None and agent.get("role_id") is not None:
        role_ids = [agent["role_id"]]
    return {
        "agent": agent,
        "prompt": next((item for item in document.prompts if _prompt_id(item) == agent.get("prompt_id")), None),
        "roles": [item for item in document.roles if item.get("role_id") in (role_ids or [])],
        "execution_profile": next((item for item in document.execution_profiles if item.get("profile_id") == agent.get("execution_profile_id")), None),
    }


def resolve_agent_composition(
    project_root: Path,
    agent_id: str,
    *,
    snapshot: AgentsConfigSnapshot | None = None,
) -> ResolvedAgentComposition:
    repository = AgentsConfigRepository()
    current = snapshot or repository.read(project_root)
    raw = next((item for item in current.document.agents if item.get("agent_id") == agent_id), None)
    if raw is None:
        raise KeyError(agent_id)
    agent = agent_definition_from_dict(raw)
    if not agent.prompt_id:
        raise ValueError(f"agent {agent_id} requires prompt_id")
    prompt = next((item for item in current.document.prompts if _prompt_id(item) == agent.prompt_id), None)
    if prompt is None:
        raise ValueError(f"agent {agent_id} references missing prompt {agent.prompt_id}")
    roles = tuple(role_from_dict(item) for item in current.document.roles if item.get("role_id") in agent.role_ids)
    if len(roles) != len(agent.role_ids):
        raise ValueError(f"agent {agent_id} references missing role")
    profile = execution_profile_from_dict(next(item for item in current.document.execution_profiles if item.get("profile_id") == agent.execution_profile_id))
    prompt_data: dict[str, Any] = prompt.to_dict() if hasattr(prompt, "to_dict") else dict(prompt)  # type: ignore[arg-type]
    agent_data = agent_definition_to_mapping(agent)
    role_data = [role_to_mapping(role) for role in roles]
    profile_data = execution_profile_to_mapping(profile)
    identity_parts = {
        "agent": agent_data,
        "prompt": prompt_data,
        "roles": sorted(role_data, key=lambda item: item["role_id"]),
        "profile": profile_data,
    }
    fingerprint = _fingerprint(identity_parts)
    identity = AgentConfigIdentity(
        agent_id, current.digest, _fingerprint(agent_data), agent.prompt_id,
        _fingerprint(prompt_data), _fingerprint(prompt_data.get("content", prompt_data.get("system_prompt", ""))),
        tuple(sorted(agent.role_ids)), _fingerprint(role_data),
        _fingerprint([cap.value for role in roles for cap in role.required_capabilities]),
        profile.profile_id, _fingerprint(profile_data), fingerprint,
    )
    return ResolvedAgentComposition(identity, roles, profile, prompt)


def resolve_agent_admission(
    composition: ResolvedAgentComposition,
    *,
    provider_evidence: Any,
    vocabulary: CapabilityVocabulary | None = None,
) -> AgentAdmission:
    vocabulary = vocabulary or CapabilityVocabulary({})
    manifest = resolve_role_manifest(composition.roles, vocabulary, provider_evidence)
    eligible_hint = getattr(provider_evidence, "eligible_instance_ids", None)
    if isinstance(provider_evidence, dict):
        eligible_hint = provider_evidence.get("eligible_instance_ids")
    allowed = set(eligible_hint) if eligible_hint is not None else None
    eligible = eligible_instance_ids(
        composition.execution_profile.instances,
        compatible=(lambda instance: instance in allowed) if allowed is not None else None,
    )
    if not eligible:
        raise ValueError("execution profile has no capability-compatible instances")
    return AgentAdmission(composition.identity, manifest, eligible, composition.prompt, composition.execution_profile)


def _prompt_id(item: Any) -> str | None:
    return item.prompt_id if hasattr(item, "prompt_id") else item.get("prompt_id")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def agent_definition_to_mapping(agent: Any) -> dict[str, Any]:
    return {"agent_id": agent.agent_id, "name": agent.name, "prompt_id": agent.prompt_id, "role_ids": agent.role_ids, "execution_profile_id": agent.execution_profile_id, "description": agent.description, "advertised_skills": agent.advertised_skills, "internal": agent.internal, "acp": agent.acp, "a2a": agent.a2a}


def role_to_mapping(role: Any) -> dict[str, Any]:
    return {"role_id": role.role_id, "instructions": role.instructions, "required_capabilities": [cap.value for cap in role.required_capabilities], "output_guidance": role.output_guidance, "runtime_tool_policy_ref": role.runtime_tool_policy_ref, "description": role.description}


def execution_profile_to_mapping(profile: Any) -> dict[str, Any]:
    return {"profile_id": profile.profile_id, "provider_id": profile.provider_id, "instances": profile.instances, "model_alias": profile.model_alias, "params": profile.params, "is_default": profile.is_default, "description": profile.description, "surface_id": profile.surface_id}
