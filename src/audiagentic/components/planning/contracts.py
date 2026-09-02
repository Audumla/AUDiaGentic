"""Typed transport contracts for the planning MCP surface.

These models describe transport shape only.  Persisted workflow legality and
cross-field rules remain owned by the planning domain functions.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

NonEmptyString = Annotated[str, Field(min_length=1)]
ItemState = Literal["pending", "in_progress", "completed", "superseded", "deprecated"]
ItemStateFilter = Literal[
    "active", "pending", "in_progress", "completed", "superseded", "deprecated", "all"
]
ReviewState = Literal["created", "considered", "closed"]
ReviewStateFilter = Literal["open", "created", "considered", "closed", "all"]
Work = Literal["S", "M", "L"]
Skill = Literal["basic", "intermediate", "advanced"]
Priority = Literal["P0", "P1", "P2", "P3"]
PageLimit = Annotated[int, Field(ge=1, le=100)]
Offset = Annotated[int, Field(ge=0)]


class _PlanningModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class PlanItemCreate(_PlanningModel):
    id: NonEmptyString | None = None
    plan: NonEmptyString
    title: NonEmptyString
    order: Annotated[int, Field(ge=0)] | None = None
    work: Work | None = None
    skill: Skill | None = None
    priority: Priority | None = None
    breadth: str | None = None
    created_by: NonEmptyString | None = Field(
        default=None,
        validation_alias=AliasChoices("created-by", "created_by", "creator_id"),
        serialization_alias="created-by",
    )


class PlanItemUpdates(_PlanningModel):
    title: str | None = None
    order: Annotated[int, Field(ge=0)] | None = None
    work: Work | None = None
    skill: Skill | None = None
    priority: Priority | None = None
    created_by: str | None = Field(
        default=None,
        validation_alias=AliasChoices("created-by", "created_by", "creator_id"),
        serialization_alias="created-by",
    )
    description: Any = None
    steps: Any = None
    detailed_solution: Any = None
    code_samples: Any = None
    files: Any = None
    validation: Any = None
    effort_risk: Any = None
    standards: Any = None
    acceptance_criteria: Any = None
    notes: Any = None


class PlanReviewCreate(_PlanningModel):
    id: NonEmptyString | None = None
    review_of: NonEmptyString = Field(
        validation_alias=AliasChoices("review-of", "review_of"),
        serialization_alias="review-of",
    )
    title: NonEmptyString
    reviewed_by: NonEmptyString | None = Field(
        default=None,
        validation_alias=AliasChoices("reviewed-by", "reviewed_by", "reviewer_id"),
        serialization_alias="reviewed-by",
    )
    reviewed_at: str | None = Field(
        default=None, validation_alias="reviewed-at", serialization_alias="reviewed-at"
    )
    notes: Any = None
    findings: Any = None
    conclusion: Any = None


class PlanReviewUpdates(_PlanningModel):
    title: str | None = None
    reviewed_by: str | None = Field(
        default=None,
        validation_alias=AliasChoices("reviewed-by", "reviewed_by", "reviewer_id"),
        serialization_alias="reviewed-by",
    )
    reviewed_at: str | None = Field(
        default=None, validation_alias="reviewed-at", serialization_alias="reviewed-at"
    )
    notes: Any = None
    findings: Any = None
    conclusion: Any = None


class ConfigUpdates(_PlanningModel):
    """Open object: implementation-specific options are descriptor-defined."""


def model_mapping(value: BaseModel | dict[str, Any]) -> dict[str, Any]:
    """Convert a validated model to the canonical mapping shape."""
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_unset=True)
    return dict(value)


def ensure_model(value: Any, model_type: type[BaseModel]) -> BaseModel:
    """Validate direct Python callers as well as MCP-created model values."""
    return value if isinstance(value, model_type) else model_type.model_validate(value)


def model_field_names(value: BaseModel | dict[str, Any]) -> set[str]:
    if isinstance(value, BaseModel):
        return set(value.model_fields_set)
    return set(value)
