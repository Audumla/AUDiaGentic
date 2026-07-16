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


def execute_recipe(
    template_path: str | Path,
    params: dict[str, str],
    context: dict[str, Any] | None = None,
) -> RecipeResult:
    """Load a recipe YAML, materialize with *params*, then provision.

    Lifecycle order: probe -> install -> configure -> verify.
    If the pre-install probe reports VERIFIED, returns early.
    On any failure the first error is returned and remaining steps are skipped.
    """
    ctx = dict(context) if context else {}

    # Load and materialize
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

    # Pre-install probe — skip if already verified
    if mat.probe is not None:
        probe_result = mat.probe.check(ctx)
        if probe_result.passed:
            return RecipeResult.ok(
                RecipeState.VERIFIED,
                status="already provisioned (pre-install probe passed)",
                details={"probe": probe_result.detail},
            )

    # Install
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

    # Configure
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

    # Verify
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
