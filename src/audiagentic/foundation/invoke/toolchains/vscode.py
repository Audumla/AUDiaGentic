from __future__ import annotations

from ..recipes.shell import ShellRecipe


def install(extension_id: str) -> ShellRecipe:
    return ShellRecipe(("code", "--install-extension", extension_id, "--force"))


def uninstall(extension_id: str) -> ShellRecipe:
    return ShellRecipe(("code", "--uninstall-extension", extension_id))
