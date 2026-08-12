"""Deterministic validation for the canonical Agents configuration document."""
from __future__ import annotations

from typing import Any

from .contracts import AgentsConfigDocument


def validate_document(document: AgentsConfigDocument) -> tuple[str, ...]:
    errors: list[str] = []

    def collect(kind: str, values: tuple[dict[str, Any], ...], key: str) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for index, raw_value in enumerate(values):
            value = raw_value.to_dict() if hasattr(raw_value, "to_dict") else raw_value
            identifier = value.get(key, value.get(key.replace("_", "-")))
            if not isinstance(identifier, str) or not identifier.strip():
                errors.append(f"{kind}[{index}].{key}: required non-empty string")
            elif identifier in result:
                errors.append(f"{kind}[{index}].{key}: duplicate id {identifier!r}")
            else:
                result[identifier] = value
        return result

    prompts = collect("prompts", document.prompts, "prompt_id")
    roles = collect("roles", document.roles, "role_id")
    profiles = collect("execution_profiles", document.execution_profiles, "profile_id")
    agents = collect("agents", document.agents, "agent_id")
    for agent_id, agent in sorted(agents.items()):
        prompt_id = agent.get("prompt_id", agent.get("prompt-id"))
        if prompt_id is not None and prompt_id not in prompts:
            errors.append(f"agents[{agent_id}].prompt_id: missing reference {prompt_id!r}")
        role_values = agent.get("role_ids", agent.get("role-ids"))
        if role_values is None and agent.get("role_id") is not None:
            role_values = [agent["role_id"]]
        if not isinstance(role_values, (list, tuple)):
            errors.append(f"agents[{agent_id}].role_ids: expected list")
        else:
            for role_id in role_values:
                if role_id not in roles:
                    errors.append(f"agents[{agent_id}].role_ids: missing reference {role_id!r}")
        profile_id = agent.get("execution_profile_id", agent.get("execution-profile-id"))
        if profile_id not in profiles:
            errors.append(f"agents[{agent_id}].execution_profile_id: missing reference {profile_id!r}")
    return tuple(sorted(errors))
