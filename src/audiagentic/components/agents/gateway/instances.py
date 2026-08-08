"""AS105/AS101: resolve ExecutionProfile.instances against providers' model-sources.yaml.

Capacity (resource-id, concurrency) lives on providers' model-sources.yaml
sources, not on a separate agents-owned taxonomy (see AS105's
correction_2026_08_08_ownership_folded_into_providers). This module is the
one seam agents uses to read those facts for dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InstanceFacts:
    """Dispatch-relevant facts for one model-sources.yaml source.

    resource_id/concurrency are None for a source that declares neither --
    such a source is not subject to shared-capacity gating and is always
    treated as available (preserves today's single-instance behavior).
    """

    source_id: str
    model_id: str | None
    resource_id: str | None
    concurrency: int | None


def resolve_instance_facts(project_root: Path, instance_ids: tuple[str, ...]) -> tuple[InstanceFacts, ...]:
    """Resolve each instance id to its dispatch-relevant facts.

    Naming a model-sources.yaml source-id is opportunistic: an instance id
    that matches a declared source picks up its resource-id/concurrency (if
    any); one that doesn't is treated as a plain, ungated model-id (the
    pre-AS105/AS101 ExecutionProfile.model_id behavior).
    """
    from audiagentic.components.providers.providers_api import resolve_instance_capacity

    capacity = resolve_instance_capacity(project_root, list(instance_ids))
    return tuple(
        InstanceFacts(
            source_id=source_id,
            model_id=capacity[source_id].get("model-id"),
            resource_id=capacity[source_id].get("resource-id"),
            concurrency=capacity[source_id].get("concurrency"),
        )
        for source_id in instance_ids
    )
