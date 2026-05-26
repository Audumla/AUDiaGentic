from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(package: str) -> ShellRecipe:
    return ShellRecipe(("cargo", "install", package))


def uninstall(package: str) -> ShellRecipe:
    return ShellRecipe(("cargo", "uninstall", package))
