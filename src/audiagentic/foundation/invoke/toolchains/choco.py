from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(package: str) -> ShellRecipe:
    return ShellRecipe(("choco", "install", "-y", package))


def uninstall(package: str) -> ShellRecipe:
    return ShellRecipe(("choco", "uninstall", "-y", package))
