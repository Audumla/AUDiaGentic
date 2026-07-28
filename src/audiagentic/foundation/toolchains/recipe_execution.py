"""Declarative recipe execution — load, materialize, provision in one call.

Connects the loader + materializer to the existing step/ probe machinery
so a YAML file and a parameter dict are sufficient to run a full install,
configure, and verify lifecycle without writing Python code.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import make_error_factory

from .probes import check_with_retry
from .recipe_contract import RecipeResult, RecipeState, run_steps
from .recipe_loader import load_recipe_from_yaml
from .recipe_materializer import materialize_recipe

_exec_err = make_error_factory("VAL", "EXEC", "recipe-execution")
logger = logging.getLogger(__name__)


_SUPPORTED_MODES = ("apply", "prune", "status", "plan", "upgrade-status", "upgrade")


def execute_recipe(
    template_path: str | Path,
    params: dict[str, str],
    context: dict[str, Any] | None = None,
) -> RecipeResult:
    """Load a recipe YAML, materialize with *params*, then provision (apply mode).

    Thin wrapper over :func:`execute_recipe_mode` preserved for existing callers.
    """
    return execute_recipe_mode(template_path, params, "apply", context)


def execute_recipe_mode(
    template_path: str | Path,
    params: dict[str, str],
    mode: str,
    context: dict[str, Any] | None = None,
) -> RecipeResult:
    """Load + materialize a recipe YAML and run one semantic mode.

    ``apply`` runs probe -> install -> configure -> verify (early-returns when the
    pre-install probe already reports VERIFIED). ``prune`` runs the declared
    uninstall steps. ``status`` runs the verify (or install) probe read-only.
    ``plan`` describes what apply would do without executing. A YAML file plus a
    parameter dict is sufficient for the whole lifecycle — no Python per recipe.
    ``upgrade`` is intentionally unavailable to a declarative recipe until it
    declares an upgrade lifecycle; this prevents apply from becoming an implicit
    package update.
    """
    if mode not in _SUPPORTED_MODES:
        return RecipeResult.fail(
            f"unsupported recipe mode: {mode!r}",
            details={"supported": list(_SUPPORTED_MODES)},
        )

    ctx = dict(context) if context else {}

    try:
        template = load_recipe_from_yaml(template_path)
    except Exception as e:  # noqa: BLE001
        return RecipeResult.fail(
            f"cannot load recipe: {e}",
            details={"path": str(template_path)},
        )

    try:
        mat = materialize_recipe(template, params)
    except Exception as e:  # noqa: BLE001
        return RecipeResult.fail(
            f"cannot materialize recipe: {e}",
            details={"path": str(template_path)},
        )

    if mode == "prune":
        return _prune(mat, ctx)
    if mode == "status":
        return _status(mat, ctx)
    if mode == "plan":
        return _plan(mat)
    if mode == "upgrade":
        return _upgrade(mat, ctx)
    if mode == "upgrade-status":
        return _upgrade_status(mat, ctx)
    return _apply(mat, ctx)


def _apply(mat: Any, ctx: dict[str, Any]) -> RecipeResult:
    # Pre-install probe — skip if already verified
    if mat.probe is not None:
        probe_result = mat.probe.check(ctx)
        if probe_result.passed:
            return RecipeResult.ok(
                RecipeState.VERIFIED,
                status="already provisioned (pre-install probe passed)",
                details={"probe": probe_result.detail},
            )

    if mat.install_steps:
        result = run_steps(
            mat.install_steps,
            ctx,
            ok_state=RecipeState.INSTALLING,
            ok_status="install steps succeeded",
            fail_prefix="install sequence failed",
        )
        if not result.success:
            return result

    if mat.configure_steps:
        result = run_steps(
            mat.configure_steps,
            ctx,
            ok_state=RecipeState.CONFIGURING,
            ok_status="configure steps succeeded",
            fail_prefix="configure sequence failed",
        )
        if not result.success:
            return result

    if mat.verify is not None:
        verify_result = check_with_retry(mat.verify, context=ctx)
        if not verify_result.passed:
            return RecipeResult.fail(
                f"verify probe failed: {verify_result.detail}",
                state=RecipeState.ERROR,
                details={"probe": verify_result.detail},
            )

    return RecipeResult.ok(
        RecipeState.VERIFIED,
        status="recipe provisioned successfully",
        details={"recipe_id": mat.recipe_id, "version": mat.recipe_version},
    )


def _prune(mat: Any, ctx: dict[str, Any]) -> RecipeResult:
    if not mat.uninstall_steps:
        return RecipeResult.ok(RecipeState.ABSENT, status="nothing to prune")
    result = run_steps(
        mat.uninstall_steps,
        ctx,
        ok_state=RecipeState.ABSENT,
        ok_status="uninstall steps succeeded",
        fail_prefix="uninstall sequence failed",
    )
    return result


def _status(mat: Any, ctx: dict[str, Any]) -> RecipeResult:
    probe = mat.verify or mat.probe
    if probe is None:
        return RecipeResult.ok(RecipeState.ABSENT, status="no status probe available")
    probe_result = check_with_retry(probe, context=ctx)
    return RecipeResult.ok(
        RecipeState.VERIFIED if probe_result.passed else RecipeState.ABSENT,
        status=probe_result.detail,
    )


def _plan(mat: Any) -> RecipeResult:
    install = len(mat.install_steps)
    configure = len(mat.configure_steps)
    return RecipeResult.ok(
        RecipeState.ABSENT,
        status=f"would run {install} install + {configure} configure step(s)",
        details={"recipe_id": mat.recipe_id, "install": install, "configure": configure},
    )


def _upgrade(mat: Any, ctx: dict[str, Any]) -> RecipeResult:
    """Run an explicitly declared upgrade sequence, never install steps."""
    if not mat.upgrade_steps:
        return RecipeResult.ok(
            RecipeState.NOT_APPLICABLE,
            status="recipe has no declared upgrade lifecycle",
            details={"recipe_id": mat.recipe_id, "version": mat.recipe_version},
        )
    result = run_steps(
        mat.upgrade_steps,
        ctx,
        ok_state=RecipeState.UPGRADING,
        ok_status="upgrade steps succeeded",
        fail_prefix="upgrade sequence failed",
    )
    if not result.success:
        return result
    if mat.verify is not None:
        verify_result = check_with_retry(mat.verify, context=ctx)
        if not verify_result.passed:
            return RecipeResult.fail(
                f"upgrade verify probe failed: {verify_result.detail}",
                details={"probe": verify_result.detail},
            )
    return RecipeResult.ok(
        RecipeState.UPGRADED,
        status="recipe upgraded successfully",
        details={"recipe_id": mat.recipe_id, "version": mat.recipe_version},
    )


def _upgrade_status(mat: Any, ctx: dict[str, Any]) -> RecipeResult:
    if not mat.upgrade_steps:
        return RecipeResult.ok(
            RecipeState.NOT_APPLICABLE,
            status="recipe has no declared upgrade lifecycle",
            details={"recipe_id": mat.recipe_id, "version": mat.recipe_version},
        )
    current = _status(mat, ctx)
    if current.state is RecipeState.ABSENT:
        return current
    return RecipeResult.ok(
        RecipeState.UPGRADE_AVAILABLE,
        status="recipe has a declared explicit upgrade lifecycle",
        details={"recipe_id": mat.recipe_id, "version": mat.recipe_version},
    )
