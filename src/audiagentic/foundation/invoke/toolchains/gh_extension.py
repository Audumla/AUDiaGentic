from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(package: str) -> ShellRecipe:
    return ShellRecipe(("gh", "extension", "install", package))


def remove(package: str) -> ShellRecipe:
    return ShellRecipe(("gh", "extension", "remove", package))
