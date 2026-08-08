"""Model instance data model and storage (AS105/AS101).

A Model Instance is a named, server-addressable place work actually runs --
the unit of capacity. The same underlying weights loaded on two GPUs are two
instances (e.g. `m27b1`, `m27b2`), each with its own concurrency. One
instance may serve several models (llama-swap-style), each with its own
concurrency when loaded -- `servable_models` is a mapping, never a flat
number, because a larger model supports fewer parallel sequences on the same
hardware. User-global config (audiagentic_home()), never project-local --
see agents_paths.model_instances_path.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError

logger = logging.getLogger(__name__)


@dataclass
class ModelInstance:
    """A named, server-addressable place work runs -- the unit of capacity."""
    instance_id: str
    resource_id: str
    servable_models: dict[str, int] = field(default_factory=dict)
    logical_model: str | None = None
    loaded_model: str | None = None
    description: str = ""

    def concurrency_for(self, model: str) -> int | None:
        """Concurrency this instance grants `model` when it is the loaded
        model, or None if this instance cannot serve that model at all."""
        return self.servable_models.get(model)


def validate_model_instance(instance: dict[str, Any]) -> list[str]:
    """Validate a model instance dict against the schema.

    Returns a list of issue strings. Empty list means valid.
    """
    issues: list[str] = []
    instance_id = instance.get("instance_id")
    if not instance_id or not isinstance(instance_id, str):
        issues.append("instance_id is required and must be a non-empty string")
    resource_id = instance.get("resource_id")
    if not resource_id or not isinstance(resource_id, str):
        issues.append("resource_id is required and must be a non-empty string")
    servable_models = instance.get("servable_models")
    if not servable_models or not isinstance(servable_models, dict):
        issues.append("servable_models is required and must be a non-empty mapping")
    else:
        for model, concurrency in servable_models.items():
            if not isinstance(model, str) or not model:
                issues.append("servable_models keys must be non-empty strings")
            if not isinstance(concurrency, int) or isinstance(concurrency, bool) or concurrency < 1:
                issues.append(
                    f"servable_models[{model!r}] concurrency must be a positive integer"
                )
    loaded_model = instance.get("loaded_model")
    if loaded_model is not None:
        if not isinstance(loaded_model, str):
            issues.append("loaded_model must be a string or null")
        elif isinstance(servable_models, dict) and loaded_model not in servable_models:
            issues.append("loaded_model must be a key of servable_models")
    if "logical_model" in instance and instance["logical_model"] is not None:
        if not isinstance(instance["logical_model"], str):
            issues.append("logical_model must be a string or null")
    if "description" in instance and instance["description"] is not None:
        if not isinstance(instance["description"], str):
            issues.append("description must be a string or null")
    return issues


def model_instance_from_dict(data: dict[str, Any]) -> ModelInstance:
    """Construct a ModelInstance from a dict with validation.

    Raises AudiaGenticError(VAL-MINST-001) if validation fails.
    """
    issues = validate_model_instance(data)
    if issues:
        raise AudiaGenticError(
            code="VAL-MINST-001",
            kind="agents",
            message="model instance failed validation",
            details={"instance_id": data.get("instance_id"), "issues": issues},
        )
    return ModelInstance(
        instance_id=str(data["instance_id"]).strip(),
        resource_id=str(data["resource_id"]).strip(),
        servable_models=dict(data["servable_models"]),
        logical_model=str(data["logical_model"]).strip() if data.get("logical_model") else None,
        loaded_model=str(data["loaded_model"]).strip() if data.get("loaded_model") else None,
        description=str(data.get("description") or "").strip(),
    )


def model_instance_to_dict(instance: ModelInstance) -> dict[str, Any]:
    """Serialize a ModelInstance to a dict for YAML round-trip."""
    return asdict(instance)


class ModelInstanceStore:
    """In-memory store for model instances with CRUD operations."""

    def __init__(self, instances: list[ModelInstance] | None = None) -> None:
        self._instances: dict[str, ModelInstance] = {}
        if instances:
            for i in instances:
                self._instances[i.instance_id] = i

    def get(self, instance_id: str) -> ModelInstance:
        """Raises AudiaGenticError(RES-MINST-001) if not found."""
        instance = self._instances.get(instance_id)
        if instance is None:
            raise AudiaGenticError(
                code="RES-MINST-001",
                kind="agents",
                message="model instance not found",
                details={"instance_id": instance_id},
            )
        return instance

    def list_all(self) -> list[ModelInstance]:
        return list(self._instances.values())

    def list_serving(self, model: str) -> list[ModelInstance]:
        """All instances that can serve `model` (in servable_models),
        regardless of what is currently loaded -- the compatible-instance
        set a profile naming this model resolves to."""
        return [i for i in self._instances.values() if model in i.servable_models]

    def add(self, instance: ModelInstance) -> None:
        """Raises AudiaGenticError(RES-MINST-002) if ID already exists."""
        if instance.instance_id in self._instances:
            raise AudiaGenticError(
                code="RES-MINST-002",
                kind="agents",
                message="model instance ID already exists",
                details={"instance_id": instance.instance_id},
            )
        self._instances[instance.instance_id] = instance

    def remove(self, instance_id: str) -> ModelInstance:
        instance = self.get(instance_id)
        del self._instances[instance_id]
        return instance

    def to_dicts(self) -> list[dict[str, Any]]:
        return [model_instance_to_dict(i) for i in self._instances.values()]

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]]) -> ModelInstanceStore:
        instances = []
        for entry in data:
            try:
                instances.append(model_instance_from_dict(entry))
            except AudiaGenticError:
                logger.warning(
                    "Skipping invalid model instance entry: %s",
                    entry.get("instance_id", "<unknown>"),
                )
        return cls(instances)
