from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(package: str) -> ShellRecipe:
    return ShellRecipe(("brew", "install", package))


def uninstall(package: str) -> ShellRecipe:
    return ShellRecipe(("brew", "uninstall", package))
