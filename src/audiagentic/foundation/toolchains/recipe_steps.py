"""Bridge between the workflow-step system and the provisioning-recipe contract.

Much of AUDiaGentic's installation logic is already expressed as probe-guarded
``WorkflowStep`` trees (see ``foundation.components.dependencies``). :class:`StepRecipe`
adapts such a tree — an install step, an uninstall step, and a presence check —
into a :class:`~.recipe_contract.ProvisioningRecipe`, so existing install logic
gains the recipe lifecycle (probe/verify/teardown) without being rewritten.

Recipes that need to *mutate* config rather than run a command should subclass
:class:`~.recipe_contract.ProvisioningRecipe` directly and use
:class:`~.config_patcher.ConfigPatcher`; this bridge is for command-driven installs.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from .recipe_contract import ProvisioningRecipe, RecipeResult, RecipeState


class _Runnable(Protocol):
    id: str

    def run(self, context: dict[str, Any], answers: Any | None = None) -> Any: ...


# StepResult statuses that mean "no failure": the work succeeded, was a no-op,
# or was skipped because a probe guard found the dependency already satisfied.
_OK_STATUSES = {"ok", "skipped", "planned"}


class StepRecipe(ProvisioningRecipe):
    """Adapt install/uninstall workflow steps + a presence check into a recipe."""

    def __init__(
        self,
        name: str,
        *,
        present_check: Callable[[], bool] | None = None,
        install_step: _Runnable | None = None,
        uninstall_step: _Runnable | None = None,
        configure_step: _Runnable | None = None,
        owned_artifacts: tuple[str, ...] = (),
    ) -> None:
        super().__init__()
        self.name = name
        self._present_check = present_check
        self._install_step = install_step
        self._uninstall_step = uninstall_step
        self._configure_step = configure_step
        self._owned = list(owned_artifacts)

    # --- helpers -------------------------------------------------------------

    def _present(self) -> bool:
        return bool(self._present_check()) if self._present_check is not None else False

    def _run_step(
        self, step: _Runnable | None, context: dict[str, Any], state: RecipeState
    ) -> RecipeResult:
        if step is None:
            return RecipeResult.ok(state, artifacts=self._owned)
        result = step.run(context)
        status = getattr(result, "status", "failed")
        if status in _OK_STATUSES:
            return RecipeResult.ok(
                state, artifacts=self._owned, details={"step_status": status}
            )
        return RecipeResult.fail(
            getattr(result, "reason", None) or f"step {step.id} returned {status}",
            details={"step_status": status},
        )

    # --- lifecycle -----------------------------------------------------------

    def probe(self, context: dict[str, Any]) -> RecipeResult:
        present = self._present()
        return RecipeResult.ok(
            RecipeState.VERIFIED if present else RecipeState.ABSENT,
            status="present" if present else "absent",
        )

    def install(self, context: dict[str, Any]) -> RecipeResult:
        return self._run_step(self._install_step, context, RecipeState.INSTALLING)

    def configure(self, context: dict[str, Any]) -> RecipeResult:
        return self._run_step(self._configure_step, context, RecipeState.CONFIGURING)

    def verify(self, context: dict[str, Any]) -> RecipeResult:
        if self._present_check is None:
            return RecipeResult.ok(RecipeState.VERIFIED, status="no presence check")
        if self._present():
            return RecipeResult.ok(RecipeState.VERIFIED, artifacts=self._owned)
        return RecipeResult.fail("presence check failed after install")

    def uninstall(self, context: dict[str, Any]) -> RecipeResult:
        return self._run_step(self._uninstall_step, context, RecipeState.ABSENT)

    def prune(self, context: dict[str, Any]) -> RecipeResult:
        # Command-driven installs own no managed config/files by default; the
        # uninstall step reverses them. Subclasses can override for cleanup.
        return RecipeResult.ok(RecipeState.ABSENT, status="nothing to prune")

    def post_uninstall_verify(self, context: dict[str, Any]) -> RecipeResult:
        if self._present_check is None:
            return RecipeResult.ok(RecipeState.ABSENT, status="no presence check")
        if not self._present():
            return RecipeResult.ok(RecipeState.ABSENT, status="removed")
        return RecipeResult.fail("still present after uninstall")


__all__ = ["StepRecipe"]
