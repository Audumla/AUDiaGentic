"""Config-driven recipe assembly for Hindsight matrix-driven integrations.

Replaces per-kind recipe classes that are purely configuration binding +
provenance stamping (GuidanceOnly, HooksInstaller) with a declarative RecipeSpec
(pattern + param bindings + status overrides) assembled at strategy-selection
time into a _RowRecipe subclass. Strategy logic, platform/source/remote-MCP
fallbacks and genuinely-custom plugin recipes remain
in code — see the SL15 classification table.

Scope (SL15): the only migrated patterns are ``no_automation`` (guidance) and
``declared_step`` (hooks). Neither carries file-path bindings or resolve_ref
hooks, so this module deliberately contains no path-policy or hook-dispatch
machinery — adding it would be zero-consumer speculation (the SL13/SL14 lesson).
When a future pattern genuinely needs those, add them with the consumer.

Schema validation runs at assembly time and raises a canonical AudiaGenticError
so a malformed spec fails loudly rather than producing a broken recipe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.memory.hindsight.recipes import _hindsight_params, _RowRecipe
from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
    ProviderRecipeResult,
    RecipeResult,
    RecipeState,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.toolchains.recipe_patterns import (
    DeclaredStepRecipe,
    InstallManifest,
    NoAutomationRecipe,
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_VALID_PATTERNS = ("no_automation", "declared_step")

#: Row-field bindings a pattern must have to build a valid delegate.
_REQUIRED_BINDINGS: dict[str, list[str]] = {
    "no_automation": [],
    "declared_step": ["install_steps", "uninstall_steps"],
}

#: Row fields a ParamBinding may reference. Guards typos in spec authoring.
ROW_FIELD_NAMES = frozenset({
    "provider_id", "display_name", "integration_type", "recipe_kind",
    "install_steps", "uninstall_steps", "configure_steps", "status_command",
    "config_artifacts", "platform_constraints", "scope", "source_status",
    "audia_action", "source_url", "source_date", "notes",
})


@dataclass(frozen=True)
class ParamBinding:
    """Maps a pattern parameter to its source (row field or literal)."""

    param_name: str
    row_field: str | None = None
    literal: Any = None


@dataclass(frozen=True)
class StatusOverride:
    """Per-method status override that bypasses the delegate's default result."""

    method: Literal["probe", "configure", "prune", "dry_run"]
    state: str
    status_text: str


@dataclass(frozen=True)
class RecipeSpec:
    """Declarative specification for assembling a recipe instance.

    The pattern selects which foundation mechanism to bind (no_automation or
    declared_step). Param bindings connect row fields or literals to the
    pattern's constructor parameters. Status overrides replace delegate
    behaviour for specific lifecycle methods.
    """

    pattern: Literal["no_automation", "declared_step"]
    params: list[ParamBinding] = field(default_factory=list)
    status_overrides: list[StatusOverride] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_recipe_spec(spec: RecipeSpec) -> list[str]:
    """Validate a RecipeSpec against schema rules. Returns errors; empty on success.

    Each error string is prefixed with its canonical VAL-RSPEC code so callers
    can surface the precise failure. :func:`assemble_hindsight_recipe` runs this
    and raises on any error.
    """
    errors: list[str] = []

    if spec.pattern not in _VALID_PATTERNS:
        errors.append(f"VAL-RSPEC-001: unknown pattern {spec.pattern!r}")

    for binding in spec.params:
        if binding.row_field and binding.literal is not None:
            errors.append(
                f"VAL-RSPEC-002: binding {binding.param_name!r} has both row_field and literal"
            )
        elif binding.row_field and binding.row_field not in ROW_FIELD_NAMES:
            errors.append(
                f"VAL-RSPEC-003: binding {binding.param_name!r} references unknown row field {binding.row_field!r}"
            )

    bound_params = {b.param_name for b in spec.params if b.row_field is not None}
    for req in _REQUIRED_BINDINGS.get(spec.pattern, []):
        if req not in bound_params:
            errors.append(
                f"VAL-RSPEC-004: pattern {spec.pattern!r} requires param binding {req!r}"
            )

    method_names = {so.method for so in spec.status_overrides}
    if len(method_names) != len(spec.status_overrides):
        errors.append("VAL-RSPEC-005: duplicate status override methods")

    return errors


# ---------------------------------------------------------------------------
# Assembler
# ---------------------------------------------------------------------------

class _AssembledBase(_RowRecipe):
    """Base for assembled recipes; carries the optional backend attribute."""

    _backend: Any = None


def assemble_hindsight_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig | None,
    spec: RecipeSpec,
) -> _RowRecipe:
    """Assemble a _RowRecipe from a RecipeSpec.

    The returned instance delegates lifecycle primitives to the matched
    foundation pattern and overrides selected methods per the spec. provision()/
    teardown() are inherited from ProvisioningRecipe via _RowRecipe — never
    overridden for declared_step, so base orchestration
    (probe→install→configure→verify) runs; no_automation overrides provision()
    to a successful skip (there is nothing to orchestrate).

    Raises:
        AudiaGenticError: VAL-RSPEC-009 if the spec fails schema validation;
            VAL-RSPEC-010 for an unknown pattern; VAL-RSPEC-011 if declared_step
            is given without a backend.
    """
    errors = validate_recipe_spec(spec)
    if errors:
        raise AudiaGenticError(
            code="VAL-RSPEC-009",
            kind="recipe-spec",
            message="invalid RecipeSpec: " + "; ".join(errors),
        )

    if spec.pattern == "no_automation":
        return _build_no_automation_assembled(row, spec)
    if spec.pattern == "declared_step":
        if backend is None:
            raise AudiaGenticError(
                code="VAL-RSPEC-011",
                kind="recipe-spec",
                message="declared_step pattern requires a non-None backend for parameter resolution",
            )
        return _build_declared_step_assembled(row, backend, spec)

    raise AudiaGenticError(
        code="VAL-RSPEC-010",
        kind="recipe-spec",
        message=f"Unknown recipe pattern {spec.pattern!r}",
    )


def _build_params_dict(spec: RecipeSpec, row: HindsightRecipeRow) -> dict[str, Any]:
    """Resolve param bindings to a concrete params dictionary."""
    params: dict[str, Any] = {}
    for binding in spec.params:
        if binding.row_field is not None:
            params[binding.param_name] = getattr(row, binding.row_field)
        else:
            params[binding.param_name] = binding.literal
    return params


def _override_map(spec: RecipeSpec) -> dict[str, StatusOverride]:
    """Map method name → StatusOverride for quick lookup."""
    return {so.method: so for so in spec.status_overrides}


def _build_no_automation_assembled(
    row: HindsightRecipeRow,
    spec: RecipeSpec,
) -> _RowRecipe:
    """Build an assembled recipe for the no_automation pattern.

    Delegates to NoAutomationRecipe with provenance stamping via _RowRecipe.
    provision() delegates to NoAutomationRecipe.provision() (a successful skip);
    the base orchestration would instead call install(), which fails because
    there is nothing to automate. Preserves the former GuidanceOnlyRecipe
    behaviour without re-implementing orchestration.
    """
    params = _build_params_dict(spec, row)
    delegate = NoAutomationRecipe(
        action_needed=params.get("action_needed", "manual setup required"),
        skip_status=params.get(
            "skip_status", "skipped: no automated Hindsight integration for this provider"
        ),
    )

    def no_auto_provision(self: _AssembledBase, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(delegate.provision(context))

    cls = _create_assembled_recipe_class(
        recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
        delegate=delegate,
        override_map=_override_map(spec),
        provision_override=no_auto_provision,
    )
    return cls(row)


def _build_declared_step_assembled(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    spec: RecipeSpec,
) -> _RowRecipe:
    """Build an assembled recipe for the declared_step pattern.

    Delegates to DeclaredStepRecipe. provision()/teardown() are inherited (base
    orchestration). configure/prune/dry_run are commonly overridden via status
    overrides for hooks-installer recipes whose core behaviour is install/uninstall.
    """
    params = _build_params_dict(spec, row)
    manifest = InstallManifest(
        install_steps=tuple(params.get("install_steps", [])),
        uninstall_steps=tuple(params.get("uninstall_steps", [])),
        status_command=params.get("status_command", ""),
        verified=params.get("verified", True),
        source_label=params.get("source_label", ""),
        gate_action=params.get("gate_action", ""),
        recipe_id=f"hindsight-{row.provider_id}",
    )
    delegate = DeclaredStepRecipe(
        manifest,
        _hindsight_params(backend),
        subject="installer",
    )

    cls = _create_assembled_recipe_class(
        recipe_kind=None,
        delegate=delegate,
        override_map=_override_map(spec),
        provision_steps_provider=lambda self: delegate.provision_steps(),
    )
    return cls(row, backend)  # type: ignore[call-arg]


def _create_assembled_recipe_class(
    *,
    recipe_kind: ProviderRecipeKind | None,
    delegate: Any,
    override_map: dict[str, StatusOverride],
    provision_steps_provider: Any = None,
    provision_override: Any = None,
) -> type[_AssembledBase]:
    """Create a dynamically-assembled _RowRecipe subclass.

    Lifecycle primitives are bound at class-creation time. The class inherits
    provision()/teardown() from ProvisioningRecipe via _RowRecipe unless a
    provision_override is supplied (no_automation).
    """
    def __init__(self, row_init: HindsightRecipeRow, backend_init: Any = None) -> None:
        _RowRecipe.__init__(self, row_init, recipe_kind=recipe_kind)
        self._backend = backend_init

    attrs: dict[str, Any] = {"__init__": __init__}
    for method_name in ("probe", "install", "configure", "verify", "uninstall", "prune", "dry_run"):
        attrs[method_name] = _make_stamp_method(method_name, override_map, delegate)

    if provision_steps_provider is not None:
        attrs["provision_steps"] = provision_steps_provider
    if provision_override is not None:
        attrs["provision"] = provision_override

    return type("_AssembledRecipe", (_AssembledBase,), attrs)


def _make_stamp_method(
    method_name: str,
    override_map: dict[str, StatusOverride],
    delegate: Any,
) -> Any:
    """Create a stamped lifecycle method for an assembled recipe class.

    Priority: status override > delegate dispatch. Every result is routed
    through _RowRecipe._stamp() (inherited by the assembled subclass), which
    surfaces row.notes as action_needed, falling back to row.audia_action.
    """
    override = override_map.get(method_name)
    if override:
        def stamped_override(self: _AssembledBase, context: dict[str, Any]) -> ProviderRecipeResult:
            return self._stamp(RecipeResult.ok(
                RecipeState(override.state),
                status=override.status_text,
                action_needed=self._row.notes,
            ))
        return stamped_override

    delegate_fn = getattr(delegate, method_name, None)
    if delegate_fn is not None:
        def stamped_delegate(self: _AssembledBase, context: dict[str, Any]) -> ProviderRecipeResult:
            return self._stamp(delegate_fn(context))
        return stamped_delegate

    def stamped_fallback(self: _AssembledBase, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(delegate.probe(context))
    return stamped_fallback


__all__ = [
    "ParamBinding",
    "RecipeSpec",
    "StatusOverride",
    "assemble_hindsight_recipe",
    "validate_recipe_spec",
]
