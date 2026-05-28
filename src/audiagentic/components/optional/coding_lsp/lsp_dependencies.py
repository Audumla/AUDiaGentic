"""LSP language server dependency specifications.

Defines install/uninstall recipes for each supported language server
so the coding-lsp component can offer automatic dependency installation
when a language is enabled but the server binary is missing.
"""
from __future__ import annotations

from audiagentic.foundation.dependencies import DependencySpec
from audiagentic.foundation.invoke.toolchains import (
    apt,
    brew,
    cargo,
    choco,
    dnf,
    npm,
    pacman,
    scoop,
    uv,
    winget,
)
from audiagentic.foundation.invoke.toolchains.detect import tool_available


def _clangd_install_recipe() -> DependencySpec:
    """Build a cross-platform install recipe for clangd."""
    from audiagentic.foundation.invoke.recipes import PlatformRecipe

    return DependencySpec(
        id="clangd",
        display_name="Clangd (C/C++ LSP)",
        check=lambda: tool_available("clangd"),
        install=PlatformRecipe(
            variants={
                "winget": winget.install("LLVM.LLVM"),
                "scoop":  scoop.install("clangd"),
                "choco":  choco.install("llvm"),
                "brew":   brew.install("clangd"),
                "apt":    apt.install("clangd"),
                "dnf":    dnf.install("clangd"),
                "pacman": pacman.install("clangd"),
            },
        ),
        uninstall=PlatformRecipe(
            variants={
                "winget": winget.uninstall("LLVM.LLVM"),
                "scoop":  scoop.uninstall("clangd"),
                "choco":  choco.uninstall("llvm"),
                "brew":   brew.uninstall("clangd"),
                "apt":    apt.remove("clangd"),
                "dnf":    dnf.remove("clangd"),
                "pacman": pacman.remove("clangd"),
            },
        ),
    )


_LSP_DEPENDENCIES: dict[str, DependencySpec] = {
    "pyright": DependencySpec(
        id="pyright",
        display_name="Pyright (Python LSP)",
        check=lambda: tool_available("pyright-langserver"),
        install=uv.install("pyright"),
        uninstall=uv.uninstall("pyright"),
    ),
    "typescript-language-server": DependencySpec(
        id="typescript-language-server",
        display_name="TypeScript Language Server",
        check=lambda: tool_available("typescript-language-server"),
        install=npm.install("typescript-language-server"),
        uninstall=npm.uninstall("typescript-language-server"),
    ),
    "rust-analyzer": DependencySpec(
        id="rust-analyzer",
        display_name="Rust Analyzer",
        check=lambda: tool_available("rust-analyzer"),
        install=cargo.install("rust-analyzer"),
        uninstall=cargo.uninstall("rust-analyzer"),
    ),
    "clangd": _clangd_install_recipe(),
}


def get_lsp_dependencies() -> dict[str, DependencySpec]:
    """Return the LSP dependency specification registry."""
    return _LSP_DEPENDENCIES
