"""Deterministic Standard Agents v0.1 projection."""
from __future__ import annotations

from typing import Any


class NonPortableProjectionError(ValueError):
    """The canonical Agent contains semantics Standard Agents cannot represent exactly."""


def project_agent(composition: dict[str, Any]) -> dict[str, Any]:
    agent = composition.get("agent") or composition
    profile = composition.get("execution_profile") or composition.get("execution-profile") or {}
    prompt = composition.get("prompt") or {}
    roles = composition.get("roles") or []
    instances = profile.get("instances") or []
    if len(instances) != 1:
        raise NonPortableProjectionError("execution_profile.instances: dynamic multi-instance scheduling is not portable")
    model = instances[0].get("model_id") or instances[0].get("model-id") if isinstance(instances[0], dict) else None
    provider = instances[0].get("provider_id") or instances[0].get("provider-id") if isinstance(instances[0], dict) else None
    if not model or not provider:
        raise NonPortableProjectionError("execution_profile.instances[0]: exact provider and model are required")
    instructions = [str(role.get("instructions", "")) for role in roles if role.get("instructions")]
    if prompt.get("content") or prompt.get("system_prompt"):
        instructions.insert(0, str(prompt.get("content") or prompt.get("system_prompt")))
    return {
        "type": "AgentDefinition",
        "id": agent.get("agent_id") or agent.get("agent-id"),
        "name": agent.get("name"),
        "kind": "ai_human",
        "instructions": "\n\n".join(instructions),
        "model": {"provider": provider, "model": model},
        "tools": list(composition.get("tools") or []),
    }
