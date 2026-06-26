"""LSP language-server install expressed as a provisioning recipe (TO07).

This is a thin refit, not a rewrite: language-server installs already run through
the generic, probe-guarded dependency workflow
(:mod:`audiagentic.foundation.components.dependencies`). Here we wrap that existing
workflow in the shared :class:`~audiagentic.foundation.toolchains.recipe_steps.StepRecipe`
so LSP gains the recipe lifecycle (probe → install → verify → uninstall) and
validates that the recipe abstraction fits a real, working consumer (RV07).
"""
from __future__ import annotations

from audiagentic.foundation.components.dependencies import (
    build_dependency_probes,
    build_dependency_workflow,
)
from audiagentic.foundation.toolchains.recipe_steps import StepRecipe

from .language_registry import LanguageSpec


def lsp_language_recipe(spec: LanguageSpec) -> StepRecipe | None:
    """Build a :class:`StepRecipe` for a language's LSP server dependency.

    Returns ``None`` when the language declares no installable dependency (its
    server is assumed to be on PATH). The recipe reuses the existing dependency
    workflow verbatim, so install/uninstall behavior is unchanged.
    """
    dep = spec.dependency
    if dep is None:
        return None

    dep_cfgs = {dep.id: dep.cfg}
    probe = build_dependency_probes(dep_cfgs).get(dep.id)
    install_step = build_dependency_workflow(
        dep_cfgs, workflow_id=spec.id, action="install"
    )
    uninstall_step = build_dependency_workflow(
        dep_cfgs, workflow_id=spec.id, action="uninstall"
    )

    return StepRecipe(
        name=f"lsp:{spec.id}",
        present_check=probe,
        install_step=install_step,
        uninstall_step=uninstall_step,
    )


__all__ = ["lsp_language_recipe"]
