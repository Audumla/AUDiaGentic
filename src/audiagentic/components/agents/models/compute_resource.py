"""Compute resource data model and storage (AS105/AS101).

A Compute Resource is the physical grouping underneath one or more Model
Instances -- a GPU, a remote host, a hosted-API account. Deliberately thin:
instances carry the concurrency, resources carry only what is needed to know
which instances contend for the same silicon and for capacity accounting.
User-global config (audiagentic_home()), never project-local -- see
agents_paths.compute_resources_path.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)

_VALID_KINDS = frozenset({"local-gpu", "remote-host", "hosted-api", "unbounded"})


@dataclass
class ComputeResource:
    """The finite thing underneath one or more Model Instances."""
    resource_id: str
    kind: str
    description: str = ""


def validate_compute_resource(resource: dict[str, Any]) -> list[str]:
    """Validate a compute resource dict against the schema.

    Returns a list of issue strings. Empty list means valid.
    """
    issues: list[str] = []
    resource_id = resource.get("resource_id")
    if not resource_id or not isinstance(resource_id, str):
        issues.append("resource_id is required and must be a non-empty string")
    kind = resource.get("kind")
    if not kind or not isinstance(kind, str):
        issues.append("kind is required and must be a non-empty string")
    elif kind not in _VALID_KINDS:
        issues.append(f"kind must be one of {sorted(_VALID_KINDS)}")
    if "description" in resource and resource["description"] is not None:
        if not isinstance(resource["description"], str):
            issues.append("description must be a string or null")
    return issues


def compute_resource_from_dict(data: dict[str, Any]) -> ComputeResource:
    """Construct a ComputeResource from a dict with validation.

    Raises AudiaGenticError(VAL-CRES-001) if validation fails.
    """
    issues = validate_compute_resource(data)
    if issues:
        raise AudiaGenticError(
            code="VAL-CRES-001",
            kind="agents",
            message="compute resource failed validation",
            details={"resource_id": data.get("resource_id"), "issues": issues},
        )
    return ComputeResource(
        resource_id=str(data["resource_id"]).strip(),
        kind=str(data["kind"]).strip(),
        description=str(data.get("description") or "").strip(),
    )


def compute_resource_to_dict(resource: ComputeResource) -> dict[str, Any]:
    """Serialize a ComputeResource to a dict for YAML round-trip."""
    return asdict(resource)


class ComputeResourceStore:
    """In-memory store for compute resources with CRUD operations."""

    def __init__(self, resources: list[ComputeResource] | None = None) -> None:
        self._resources: dict[str, ComputeResource] = {}
        if resources:
            for r in resources:
                self._resources[r.resource_id] = r

    def get(self, resource_id: str) -> ComputeResource:
        """Raises AudiaGenticError(RES-CRES-001) if not found."""
        resource = self._resources.get(resource_id)
        if resource is None:
            raise AudiaGenticError(
                code="RES-CRES-001",
                kind="agents",
                message="compute resource not found",
                details={"resource_id": resource_id},
            )
        return resource

    def list_all(self) -> list[ComputeResource]:
        return list(self._resources.values())

    def add(self, resource: ComputeResource) -> None:
        """Raises AudiaGenticError(RES-CRES-002) if ID already exists."""
        if resource.resource_id in self._resources:
            raise AudiaGenticError(
                code="RES-CRES-002",
                kind="agents",
                message="compute resource ID already exists",
                details={"resource_id": resource.resource_id},
            )
        self._resources[resource.resource_id] = resource

    def remove(self, resource_id: str) -> ComputeResource:
        resource = self.get(resource_id)
        del self._resources[resource_id]
        return resource

    def to_dicts(self) -> list[dict[str, Any]]:
        return [compute_resource_to_dict(r) for r in self._resources.values()]

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]]) -> ComputeResourceStore:
        resources = []
        for entry in data:
            try:
                resources.append(compute_resource_from_dict(entry))
            except AudiaGenticError:
                logger.warning(
                    "Skipping invalid compute resource entry: %s",
                    entry.get("resource_id", "<unknown>"),
                )
        return cls(resources)
