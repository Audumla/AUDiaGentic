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
    capabilities: dict[str, ResolvedCapability] = {}
    for role in sorted(roles, key=lambda item: item.role_id):
        for requirement in role.required_capabilities:
            capability_id = requirement if isinstance(requirement, CapabilityRequirementId) else CapabilityRequirementId(requirement)
            if capability_id.value in capabilities:
                continue
            launch = vocabulary.resolve(capability_id)
            capabilities[capability_id.value] = ResolvedCapability(capability_id, (), launch)
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
