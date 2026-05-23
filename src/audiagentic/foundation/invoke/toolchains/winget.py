from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(package_id: str, *extra_flags: str) -> ShellRecipe:
    return ShellRecipe(("winget", "install", "--id", package_id, "-e") + extra_flags)


def uninstall(package_id: str, *extra_flags: str) -> ShellRecipe:
    return ShellRecipe(("winget", "uninstall", "--id", package_id, "-e") + extra_flags)
