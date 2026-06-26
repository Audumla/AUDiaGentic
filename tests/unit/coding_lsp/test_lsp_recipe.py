from __future__ import annotations

from audiagentic.components.coding_lsp.language_registry import (
    LanguageDependency,
    LanguageSpec,
)
from audiagentic.components.coding_lsp.lsp_recipe import lsp_language_recipe
from audiagentic.foundation.toolchains.recipe_contract import RecipeState


def _spec(dependency=None):
    return LanguageSpec(
        id="demo",
        display_name="Demo",
        language_id="demo",
        command=("demo-ls", "--stdio"),
        file_extensions=(".demo",),
        dependency=dependency,
    )


def test_no_dependency_returns_none():
    assert lsp_language_recipe(_spec()) is None


def test_recipe_built_from_dependency(tmp_path):
    marker = tmp_path / "server-binary"
    dep = LanguageDependency(
        id="demo-ls",
        cfg={"probe": f"path:{marker}", "toolchain": "npm", "package": "demo-ls"},
    )
    recipe = lsp_language_recipe(_spec(dep))
    assert recipe is not None
    assert recipe.name == "lsp:demo"

    # probe reflects the existing dependency probe (path check)
    assert recipe.probe({}).state is RecipeState.ABSENT
    marker.write_text("x", encoding="utf-8")
    assert recipe.probe({}).state is RecipeState.VERIFIED


def test_recipe_reuses_dependency_workflow_steps(tmp_path):
    marker = tmp_path / "bin"
    dep = LanguageDependency(
        id="demo-ls",
        cfg={"probe": f"path:{marker}", "toolchain": "npm", "package": "demo-ls"},
    )
    recipe = lsp_language_recipe(_spec(dep))
    assert recipe is not None
    # install/uninstall steps are real workflow steps wired from the dep config
    assert recipe._install_step is not None
    assert recipe._uninstall_step is not None
