from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.toolchains.recipe_contract import RecipeState
from audiagentic.foundation.toolchains.recipe_execution import execute_recipe_mode


def _recipe(path: Path) -> Path:
    path.write_text(
        """recipe-id: upgrade-fixture
recipe-version: \"1\"
parameters:
  - name: TARGET
    required: true
lifecycle:
  install-steps: []
  upgrade-steps:
    - type: write-file
      id: upgrade-marker
      path: \"{TARGET}\"
      content: upgraded
""",
        encoding="utf-8",
    )
    return path


def test_declarative_upgrade_runs_only_declared_upgrade_steps(tmp_path: Path) -> None:
    recipe = _recipe(tmp_path / "recipe.yaml")
    target = tmp_path / "marker.txt"

    result = execute_recipe_mode(recipe, {"TARGET": str(target)}, "upgrade")

    assert result.success is True, result.error
    assert result.state is RecipeState.UPGRADED
    assert target.read_text(encoding="utf-8") == "upgraded"


def test_declarative_upgrade_is_not_applicable_without_steps(tmp_path: Path) -> None:
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        """recipe-id: no-upgrade-fixture
recipe-version: \"1\"
parameters: []
lifecycle:
  install-steps: []
  probe:
    type: file-exists
    path: marker
""",
        encoding="utf-8",
    )

    result = execute_recipe_mode(recipe, {}, "upgrade")

    assert result.success is True
    assert result.state is RecipeState.NOT_APPLICABLE
