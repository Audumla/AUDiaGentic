from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(package: str) -> ShellRecipe:
    return ShellRecipe(("sudo", "pacman", "-S", "--noconfirm", package))


def remove(package: str) -> ShellRecipe:
    return ShellRecipe(("sudo", "pacman", "-R", "--noconfirm", package))
