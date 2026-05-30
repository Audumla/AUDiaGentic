"""LSP language server dependency specifications."""
from __future__ import annotations

from audiagentic.foundation.dependencies import DependencySpec, _PlatformStep
from audiagentic.foundation.toolchains import (
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
from audiagentic.foundation.toolchains.detect import tool_available

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
    "clangd": DependencySpec(
        id="clangd",
        display_name="Clangd (C/C++ LSP)",
        check=lambda: tool_available("clangd"),
        install=_PlatformStep(variants={
            "winget": winget.install("LLVM.LLVM"),
            "scoop":  scoop.install("clangd"),
            "choco":  choco.install("llvm"),
            "brew":   brew.install("clangd"),
            "apt":    apt.install("clangd"),
            "dnf":    dnf.install("clangd"),
            "pacman": pacman.install("clangd"),
        }),
        uninstall=_PlatformStep(variants={
            "winget": winget.uninstall("LLVM.LLVM"),
            "scoop":  scoop.uninstall("clangd"),
            "choco":  choco.uninstall("llvm"),
            "brew":   brew.uninstall("clangd"),
            "apt":    apt.remove("clangd"),
            "dnf":    dnf.remove("clangd"),
            "pacman": pacman.remove("clangd"),
        }),
    ),
}


def get_lsp_dependencies() -> dict[str, DependencySpec]:
    return _LSP_DEPENDENCIES
