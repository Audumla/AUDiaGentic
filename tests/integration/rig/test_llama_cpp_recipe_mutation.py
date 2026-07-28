"""Clean-room mutation gate for the owned llama.cpp recipe (Docker-safe)."""
from __future__ import annotations

from pathlib import Path

from audiagentic.foundation.toolchains.recipe_contract import RecipeState
from audiagentic.runtime.rig.embedded import recipe as recipe_module


def test_owned_recipe_installs_then_reports_current_and_upgrades(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "rig-bin"
    installs: list[Path] = []

    class Asset:
        version = "b-test"
        sha256 = "a" * 64
        executable = "llama-server"

    monkeypatch.setattr(recipe_module, "load_llama_cpp_release_asset", lambda: Asset())

    def install(*, target_bin_dir: Path) -> None:
        installs.append(target_bin_dir)
        payload = target_bin_dir / "llama-server" / "linux"
        payload.mkdir(parents=True, exist_ok=True)
        (payload / "llama-server").write_text("fixture", encoding="utf-8")
        (payload / ".audiagentic-llama-cpp.json").write_text(
            '{"release-version":"b-test","sha256":"' + "a" * 64 + '"}', encoding="utf-8"
        )

    monkeypatch.setattr(recipe_module, "platform_dir_name", lambda: "linux")
    monkeypatch.setattr(recipe_module, "update_binaries", install)
    recipe = recipe_module.llama_cpp_recipe(target)

    assert recipe.probe({}).state is RecipeState.ABSENT
    assert recipe.provision({}).success
    assert recipe.probe({}).state is RecipeState.VERIFIED
    assert recipe.upgrade_status({}).state is RecipeState.VERIFIED

    provenance = target / "llama-server" / "linux" / ".audiagentic-llama-cpp.json"
    provenance.write_text('{"release-version":"old","sha256":"old"}', encoding="utf-8")
    assert recipe.upgrade_status({}).state is RecipeState.UPGRADE_AVAILABLE
    assert recipe.upgrade({}).state is RecipeState.UPGRADED
    assert installs == [target, target]
