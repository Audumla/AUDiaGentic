from __future__ import annotations

from ..recipes.shell import ShellRecipe
from .detect import privilege_prefix


def install(package: str) -> ShellRecipe:
    return ShellRecipe((*privilege_prefix(), "pacman", "-S", "--noconfirm", package))


def remove(package: str) -> ShellRecipe:
    return ShellRecipe((*privilege_prefix(), "pacman", "-R", "--noconfirm", package))
