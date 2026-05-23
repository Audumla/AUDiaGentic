from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(package: str) -> ShellRecipe:
    return ShellRecipe(("sudo", "dnf", "install", "-y", package))


def remove(package: str) -> ShellRecipe:
    return ShellRecipe(("sudo", "dnf", "remove", "-y", package))
