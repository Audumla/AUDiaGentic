"""Owned provisioning recipe for the pinned llama.cpp payload."""
from __future__ import annotations

import shutil
from pathlib import Path

from audiagentic.foundation.toolchains.recipe_contract import (
    ProvisioningRecipe,
    RecipeResult,
    RecipeState,
)
from audiagentic.runtime.rig.constants import platform_dir_name
from audiagentic.runtime.rig.embedded.binaries import installed_release, update_binaries
from audiagentic.runtime.rig.embedded.release_manifest import load_llama_cpp_release_asset


class LlamaCppRecipe(ProvisioningRecipe):
    """One owned, pinned artifact with offline status and explicit upgrade."""

    def __init__(self, target_bin_dir: Path) -> None:
        super().__init__()
        self.target_bin_dir = target_bin_dir

    @property
    def target_dir(self) -> Path:
        return self.target_bin_dir / "llama-server" / platform_dir_name()

    def probe(self, context: dict[str, object]) -> RecipeResult:
        declared = load_llama_cpp_release_asset()
        current = installed_release(self.target_dir)
        binary = self.target_dir / declared.executable
        if current is None or not binary.is_file():
            return RecipeResult.ok(RecipeState.ABSENT, status="llama.cpp is not installed")
        details = {"declared-version": declared.version, "installed": current}
        if current.get("release-version") != declared.version or current.get("sha256") != declared.sha256:
            return RecipeResult.ok(RecipeState.ABSENT, status="llama.cpp provenance differs from declaration", details=details)
        return RecipeResult.ok(RecipeState.VERIFIED, status="llama.cpp matches pinned declaration", details=details)

    def install(self, context: dict[str, object]) -> RecipeResult:
        update_binaries(target_bin_dir=self.target_bin_dir)
        return RecipeResult.ok(RecipeState.INSTALLING, status="llama.cpp installed")

    def configure(self, context: dict[str, object]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.CONFIGURING, status="llama.cpp requires no configuration")

    def verify(self, context: dict[str, object]) -> RecipeResult:
        return self.probe(context)

    def upgrade_status(self, context: dict[str, object]) -> RecipeResult:
        current = self.probe(context)
        if current.state is RecipeState.VERIFIED:
            return current
        if installed_release(self.target_dir) is None:
            return RecipeResult.ok(RecipeState.ABSENT, status="llama.cpp is absent; install is required")
        return RecipeResult.ok(RecipeState.UPGRADE_AVAILABLE, status="llama.cpp differs from pinned declaration", details=current.details)

    def upgrade(self, context: dict[str, object]) -> RecipeResult:
        status = self.upgrade_status(context)
        if status.state is RecipeState.ABSENT:
            return status
        if status.state is RecipeState.VERIFIED:
            return status
        update_binaries(target_bin_dir=self.target_bin_dir)
        verified = self.probe(context)
        return RecipeResult.ok(RecipeState.UPGRADED, status="llama.cpp upgraded", details=verified.details) if verified.state is RecipeState.VERIFIED else verified

    def uninstall(self, context: dict[str, object]) -> RecipeResult:
        if installed_release(self.target_dir) is None:
            return RecipeResult.ok(RecipeState.ABSENT, status="no owned llama.cpp payload")
        shutil.rmtree(self.target_dir)
        return RecipeResult.ok(RecipeState.ABSENT, status="owned llama.cpp payload removed")

    def prune(self, context: dict[str, object]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.ABSENT, status="no llama.cpp configuration to prune")


def llama_cpp_recipe(target_bin_dir: Path) -> LlamaCppRecipe:
    return LlamaCppRecipe(target_bin_dir)


__all__ = ["LlamaCppRecipe", "llama_cpp_recipe"]
