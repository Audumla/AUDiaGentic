"""Pure Role capability resolver."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from audiagentic.components.agents.models.role import Role

from .contracts import CapabilityRequirementId, ResolvedCapability, RoleManifest
from .vocabulary import CapabilityVocabulary


def resolve_role_manifest(roles: tuple[Role, ...], vocabulary: CapabilityVocabulary, evidence: Any) -> RoleManifest:
    role_ids = tuple(sorted(role.role_id for role in roles))
    if len(role_ids) != len(set(role_ids)):
        raise ValueError("duplicate role IDs")
    raw_facts = getattr(evidence, "facts", evidence)
    if isinstance(evidence, dict):
        raw_facts = evidence.get("facts", evidence.get("capabilities", ()))
    if raw_facts is None or isinstance(raw_facts, (str, bytes)):
        facts = ()
    else:
        try:
            facts = tuple(raw_facts)
        except TypeError:
            facts = ()

    def fact_value(fact: Any, key: str, default: Any = None) -> Any:
        return fact.get(key, default) if isinstance(fact, dict) else getattr(fact, key, default)

    capabilities: dict[str, ResolvedCapability] = {}
    for role in sorted(roles, key=lambda item: item.role_id):
        for requirement in role.required_capabilities:
            capability_id = requirement if isinstance(requirement, CapabilityRequirementId) else CapabilityRequirementId(requirement)
            if capability_id.value in capabilities:
                continue
            launch = vocabulary.resolve(capability_id)
            matching = [fact for fact in facts if fact_value(fact, "capability_id") == capability_id.value]
            supported = [fact for fact in matching if str(fact_value(fact, "support_assessment", "supported")).lower() not in {"no", "unsupported", "blocked", "false"}]
            if not supported:
                raise ValueError(f"required capability lacks positive provider evidence: {capability_id.value}")
            evidence_ids = tuple(
                str(fact_value(fact, "evidence_id") or fact_value(fact, "source") or f"provider-capability:{capability_id.value}")
                for fact in supported
            )
            capabilities[capability_id.value] = ResolvedCapability(capability_id, evidence_ids, launch)
    canonical = [
        {
            "id": item.requirement_id.value,
            "evidence": item.evidence_ids,
            "launch": {
                "mcp": item.launch.mcp_server_ids,
                "environment": item.launch.environment,
                "arguments": item.launch.arguments,
            },
        }
        for item in capabilities.values()
    ]
    fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return RoleManifest("v1", role_ids, tuple(capabilities.values()), fingerprint)
