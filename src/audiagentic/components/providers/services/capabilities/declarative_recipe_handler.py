"""Declarative-recipe handler adapter — provider-owned seam (CC41 Activity 6).

Binds a declarative YAML recipe to a typed provider family without creating
a universal family or crossing component boundaries. Foundation owns generic
recipe loading/catalogue/materialization/execution only. This module imports
foundation primitives and wraps them in a ``RecipeHandler``-compatible closure
for use from the existing ``FamilyRegistrar`` table shape.

Each owner retains its family-specific Request/Result contracts and explicitly
selects recipe ids. No CC41 family id or universal ``declarative-lifecycle``
family is needed.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from audiagentic.foundation.steps import SequenceStep, planned_commands
from audiagentic.foundation.toolchains.recipe_catalogue import make_catalogue
from audiagentic.foundation.toolchains.recipe_contract import (
    RecipeResult,
    RecipeState,
)
from audiagentic.foundation.toolchains.recipe_materializer import materialize_recipe
from audiagentic.foundation.toolchains.recipe_patterns import (
    DeclaredStepRecipe,
    InstallManifest,
    run_recipe_mode,
)

from .recipe_definitions import RecipeHandler

# ---------------------------------------------------------------------------
# DeclarativeStepRecipe — wraps a MaterializedRecipe
# ---------------------------------------------------------------------------


class _DeclarativeStepRecipe(DeclaredStepRecipe):
    """DeclaredStepRecipe backed by a pre-materialized recipe.

    Overrides the step-driven lifecycle methods to use the materializer's
    typed steps and probes directly, bypassing the raw-dict -> factory round-
    trip that InstallManifest normally requires.
    """

    def __init__(self, materialized: Any, params: dict[str, str]) -> None:
        self._mat = materialized
        manifest = InstallManifest(
            install_steps=(),
            uninstall_steps=(),
            status_command="",
            verified=True,
            source_label="declarative",
            gate_action="",
            recipe_id=materialized.recipe_id,
            configure_steps=(),
            verify_probe=None,
            dry_run_steps=(),
        )
        super().__init__(manifest, params, subject="recipe")

    def probe(self, context: dict[str, Any]) -> RecipeResult:
        if self._mat.probe is None:
            return RecipeResult.ok(RecipeState.ABSENT, status="no probe defined")
        try:
            result = self._mat.probe.check(context)
        except Exception as exc:  # noqa: BLE001
            return RecipeResult.fail(f"probe failed: {exc}")
        return RecipeResult.ok(
            RecipeState.VERIFIED if result.passed else RecipeState.ABSENT,
            status=result.detail,
        )

    def install(self, context: dict[str, Any]) -> RecipeResult:
        if not self._mat.install_steps:
            return RecipeResult.fail("no install steps in recipe")
        seq = SequenceStep(
            list(self._mat.install_steps),
            id="install-sequence",
            compensate_on_failure=True,
        )
        result = seq.run(context)
        if result.status == "ok":
            return RecipeResult.ok(RecipeState.INSTALLING, status="recipe install succeeded")
        return RecipeResult.fail(
            f"recipe install failed: {result.reason or 'unknown'}",
            details={"steps": result.outputs.get("steps", [])},
        )

    def configure(self, context: dict[str, Any]) -> RecipeResult:
        if not self._mat.configure_steps:
            return RecipeResult.ok(RecipeState.CONFIGURING, status="no config steps")
        seq = SequenceStep(
            list(self._mat.configure_steps),
            id="configure-sequence",
            compensate_on_failure=True,
        )
        result = seq.run(context)
        if result.status == "ok":
            return RecipeResult.ok(RecipeState.CONFIGURING, status="recipe configured")
        return RecipeResult.fail(
            f"recipe configure failed: {result.reason or 'unknown'}",
            details={"steps": result.outputs.get("steps", [])},
        )

    def verify(self, context: dict[str, Any]) -> RecipeResult:
        if self._mat.verify is not None:
            try:
                result = self._mat.verify.check(context)
            except Exception as exc:  # noqa: BLE001
                return RecipeResult.fail(f"verify failed: {exc}")
            return RecipeResult.ok(
                RecipeState.VERIFIED if result.passed else RecipeState.ABSENT,
                status=result.detail,
            )
        return RecipeResult.ok(
            RecipeState.VERIFIED, status="recipe completed; no verify probe"
        )

    def dry_run(self, context: dict[str, Any]) -> RecipeResult:
        declared = (
            self._mat.dry_run_steps
            or (*self._mat.install_steps, *self._mat.configure_steps)
        )
        if not declared:
            return RecipeResult.ok(RecipeState.ABSENT, status="nothing to do")
        planned = [
            cmd for step in declared for cmd in planned_commands(step, context)
        ]
        return RecipeResult.ok(
            RecipeState.ABSENT,
            status=f"would run {len(planned)} command(s)",
            artifacts=[" ".join(cmd) for cmd in planned],
        )

    def uninstall(self, context: dict[str, Any]) -> RecipeResult:
        if not self._mat.uninstall_steps:
            return RecipeResult.fail("no uninstall steps in recipe")
        seq = SequenceStep(
            list(self._mat.uninstall_steps),
            id="uninstall-sequence",
            compensate_on_failure=True,
        )
        result = seq.run(context)
        if result.status == "ok":
            return RecipeResult.ok(RecipeState.ABSENT, status="recipe uninstall succeeded")
        return RecipeResult.fail(
            f"recipe uninstall failed: {result.reason or 'unknown'}",
            details={"steps": result.outputs.get("steps", [])},
        )


# ---------------------------------------------------------------------------
# Factory: make a RecipeHandler from declarative recipe + mappers
# ---------------------------------------------------------------------------

def make_declarative_handler(
    provider_id: str,
    project_root: Path,
    recipe_id: str,
    request_to_params: Callable[[object], dict[str, str]],
    result_mapper: Callable[[RecipeResult], object],
) -> RecipeHandler:
    """Factory that returns a RecipeHandler closure backed by a declarative recipe.

    The handler resolves the recipe from the catalogue at construction time,
    then on each invocation maps the typed family request to string parameters,
    materializes the recipe, and dispatches through run_recipe_mode. The result
    is mapped back through ``result_mapper`` to the family's typed result.

    This is boring: no discovery, no new registry, no plugin system, no new
    lifecycle engine. The FamilyPin remains code-owned by the family.
    """
    catalogue = make_catalogue(project_root)
    entry = catalogue.get_recipe(recipe_id)
    template = entry.template

    def handler(
        mode: str, payload: object, ownership_scope: object | None
    ) -> object:
        params = request_to_params(payload)
        mat = materialize_recipe(template, params)
        recipe = _DeclarativeStepRecipe(mat, params)
        context = {
            "provider_id": provider_id,
            "project_root": str(project_root),
            "ownership_scope": ownership_scope,
        }
        inner_result = run_recipe_mode(recipe, mode, context)
        return result_mapper(inner_result)

    return handler


__all__ = [
    "make_declarative_handler",
]
