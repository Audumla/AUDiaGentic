"""Immutable capability contracts owned by Agents."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class CapabilityRequirementId:
    value: str


@dataclass(frozen=True, slots=True)
class LaunchContribution:
    mcp_server_ids: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()
    arguments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolvedCapability:
    requirement_id: CapabilityRequirementId
    evidence_ids: tuple[str, ...]
    launch: LaunchContribution


@dataclass(frozen=True, slots=True)
class RoleManifest:
    contract_version: str
    role_ids: tuple[str, ...]
    capabilities: tuple[ResolvedCapability, ...]
    fingerprint: str
