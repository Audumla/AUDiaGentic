"""Declarative recipe loader — YAML to frozen validated template.

Strict boundary: raw Mapping exists only inside this module. Callers receive
frozen, schema-validated objects and cannot mutate recipe definitions after
loading.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from audiagentic.foundation.contracts.errors import make_error_factory
from audiagentic.foundation.logging.redaction import is_sensitive_key

_recipe_err = make_error_factory("VAL", "REC", "recipe-loader")

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "recipes"
    / "declarative-recipe.schema.json"
)


def _load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Frozen template types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RecipeParameter:
    """A v1 string parameter declaration."""

    name: str
    required: bool = False
    default: str | None = None
    sensitive: bool = False

    @property
    def is_sensitive(self) -> bool:
        return self.sensitive or is_sensitive_key(self.name)


@dataclass(frozen=True)
class ValidatedProbeTemplate:
    """Schema-checked probe data. No raw dict escapes this class."""

    type: str  # "command", "file-exists", "config-key", "composite"
    data: dict[str, Any]


def _make_probe(raw: dict[str, Any]) -> ValidatedProbeTemplate:
    if "type" not in raw:
        raise _recipe_err(3, "probe missing 'type' field")
    return ValidatedProbeTemplate(type=raw["type"], data=dict(raw))


@dataclass(frozen=True)
class ValidatedStepTemplate:
    """Schema-checked step data. No raw dict escapes this class."""

    type: str  # one of the 9 registered step types
    id: str
    data: dict[str, Any]


def _make_step(raw: dict[str, Any]) -> ValidatedStepTemplate:
    if "type" not in raw:
        raise _recipe_err(4, "step missing 'type' field")
    step_id = raw.get("id")
    if not step_id:
        raise _recipe_err(4, "step missing 'id' field")
    return ValidatedStepTemplate(type=raw["type"], id=str(step_id), data=dict(raw))


@dataclass(frozen=True)
class RecipeLifecycleTemplate:
    """Private lifecycle mechanics. Public modes forbidden."""

    probe: ValidatedProbeTemplate | None = None
    install_steps: tuple[ValidatedStepTemplate, ...] = field(default_factory=tuple)
    configure_steps: tuple[ValidatedStepTemplate, ...] = field(default_factory=tuple)
    verify: ValidatedProbeTemplate | None = None
    uninstall_steps: tuple[ValidatedStepTemplate, ...] = field(default_factory=tuple)
    dry_run_steps: tuple[ValidatedStepTemplate, ...] = field(default_factory=tuple)

    def _check_empty(self) -> None:
        if not self.install_steps and not self.probe and not self.verify:
            raise _recipe_err(5, "empty lifecycle definition — no probe, install, or verify")


@dataclass(frozen=True)
class DeclarativeRecipeTemplate:
    """Frozen validated recipe template loaded from YAML.

    Source path and version are diagnostic metadata only — they do not affect
    recipe semantics.
    """

    recipe_id: str
    recipe_version: str
    description: str = ""
    provenance_ref: str | None = None
    parameters: tuple[RecipeParameter, ...] = field(default_factory=tuple)
    lifecycle: RecipeLifecycleTemplate = field(default_factory=RecipeLifecycleTemplate)
    source_path: str = ""
    schema_version: str = "v1"

    def _check_duplicates(self) -> None:
        seen_params: set[str] = set()
        for p in self.parameters:
            if p.name in seen_params:
                raise _recipe_err(6, f"duplicate parameter name {p.name!r}")
            seen_params.add(p.name)

        seen_step_ids: set[str] = set()
        for phase in ("install_steps", "configure_steps", "uninstall_steps", "dry_run_steps"):
            steps = getattr(self.lifecycle, phase)
            for s in steps:
                if s.id in seen_step_ids:
                    raise _recipe_err(7, f"duplicate step id {s.id!r} in {phase}")
                seen_step_ids.add(s.id)

    def to_mapping(self) -> dict[str, Any]:
        """Deterministic mapping for round-trip validation."""
        return {
            "recipe-id": self.recipe_id,
            "recipe-version": self.recipe_version,
            "description": self.description,
            "provenance-ref": self.provenance_ref,
            "parameters": [
                {
                    "name": p.name,
                    **({"required": p.required} if p.required else {}),
                    **({"default": p.default} if p.default is not None else {}),
                    **({"sensitive": p.sensitive} if p.sensitive else {}),
                }
                for p in self.parameters
            ],
            "lifecycle": {
                **({"probe": self.lifecycle.probe.data} if self.lifecycle.probe else {}),
                "install-steps": [s.data for s in self.lifecycle.install_steps],
                **(
                    {"configure-steps": [s.data for s in self.lifecycle.configure_steps]}
                    if self.lifecycle.configure_steps
                    else {}
                ),
                **({"verify": self.lifecycle.verify.data} if self.lifecycle.verify else {}),
                **(
                    {
                        "uninstall-steps": [
                            s.data for s in self.lifecycle.uninstall_steps
                        ]
                    }
                    if self.lifecycle.uninstall_steps
                    else {}
                ),
                **(
                    {
                        "dry-run-steps": [s.data for s in self.lifecycle.dry_run_steps]
                    }
                    if self.lifecycle.dry_run_steps
                    else {}
                ),
            },
        }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_recipe_from_yaml(path: str | Path) -> DeclarativeRecipeTemplate:
    """Read YAML, validate schema, return one frozen template.

    Resolution of callables, commands, paths, secrets, probes, and steps
    happens during trusted materialization — not here.
    """
    from jsonschema import Draft202012Validator

    p = Path(path)
    if not p.exists():
        raise _recipe_err(8, f"recipe file not found: {p}")

    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise _recipe_err(9, f"recipe YAML must be a mapping at top level: {p}")

    schema = _load_schema()
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(raw))
    if errors:
        msgs = [e.message for e in errors]
        raise _recipe_err(1, "schema validation failed", messages=msgs, path=str(p))

    # Build parameters
    params: tuple[RecipeParameter, ...] = tuple()
    for pdef in raw.get("parameters", []):
        params += (
            RecipeParameter(
                name=str(pdef["name"]),
                required=bool(pdef.get("required", False)),
                default=pdef.get("default"),
                sensitive=bool(pdef.get("sensitive", False)),
            ),
        )

    # Build lifecycle
    lifecycle_raw = raw.get("lifecycle", {})

    def _build_steps(step_defs: list[dict[str, Any]]) -> tuple[ValidatedStepTemplate, ...]:
        return tuple(_make_step(s) for s in step_defs)

    probe_t: ValidatedProbeTemplate | None = None
    if "probe" in lifecycle_raw:
        probe_t = _make_probe(lifecycle_raw["probe"])

    verify_t: ValidatedProbeTemplate | None = None
    if "verify" in lifecycle_raw:
        verify_t = _make_probe(lifecycle_raw["verify"])

    lifecycle = RecipeLifecycleTemplate(
        probe=probe_t,
        install_steps=_build_steps(lifecycle_raw.get("install-steps", [])),
        configure_steps=_build_steps(lifecycle_raw.get("configure-steps", [])),
        verify=verify_t,
        uninstall_steps=_build_steps(lifecycle_raw.get("uninstall-steps", [])),
        dry_run_steps=_build_steps(lifecycle_raw.get("dry-run-steps", [])),
    )

    template = DeclarativeRecipeTemplate(
        recipe_id=raw["recipe-id"],
        recipe_version=raw["recipe-version"],
        description=raw.get("description", ""),
        provenance_ref=raw.get("provenance-ref"),
        parameters=params,
        lifecycle=lifecycle,
        source_path=str(p),
    )

    lifecycle._check_empty()
    template._check_duplicates()
    return template


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------
__all__ = [
    "DeclarativeRecipeTemplate",
    "load_recipe_from_yaml",
    "RecipeLifecycleTemplate",
    "RecipeParameter",
    "ValidatedProbeTemplate",
    "ValidatedStepTemplate",
]
