from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(package: str) -> ShellRecipe:
    return ShellRecipe(("npm", "install", "-g", package))


def uninstall(package: str) -> ShellRecipe:
    return ShellRecipe(("npm", "uninstall", "-g", package))
