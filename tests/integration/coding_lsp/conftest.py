"""Integration test fixtures for coding_lsp component."""
from __future__ import annotations

import shutil

import pytest

requires_pyright = pytest.mark.skipif(
    shutil.which("pyright") is None,
    reason="pyright not on PATH — install to run this test",
)

requires_tsserver = pytest.mark.skipif(
    shutil.which("typescript-language-server") is None,
    reason="typescript-language-server not on PATH",
)

requires_rust_analyzer = pytest.mark.skipif(
    shutil.which("rust-analyzer") is None,
    reason="rust-analyzer not on PATH",
)

requires_clangd = pytest.mark.skipif(
    shutil.which("clangd") is None,
    reason="clangd not on PATH",
)
