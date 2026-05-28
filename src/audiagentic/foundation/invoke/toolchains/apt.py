from __future__ import annotations

from ..recipes.sequence import SequenceRecipe
from ..recipes.shell import ShellRecipe
from .detect import privilege_prefix


def install(package: str) -> SequenceRecipe:
    prefix = privilege_prefix()
    return SequenceRecipe(steps=(
        ShellRecipe((*prefix, "apt-get", "update", "-q")),
        ShellRecipe((*prefix, "apt-get", "install", "-y", package)),
    ))


def remove(package: str) -> ShellRecipe:
    return ShellRecipe((*privilege_prefix(), "apt-get", "remove", "-y", package))
