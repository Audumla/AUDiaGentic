from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(package: str, *pre_flags: str) -> ShellRecipe:
    """Build a uv tool install recipe.

    pre_flags are inserted between 'uv tool install' and the package name,
    matching uv's flag-before-package convention.
    """
    return ShellRecipe(("uv", "tool", "install") + pre_flags + (package,))


def uninstall(package: str) -> ShellRecipe:
    return ShellRecipe(("uv", "tool", "uninstall", package))
