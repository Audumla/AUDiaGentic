"""Integration test fixtures for coding_lsp component.

Language server binaries are installed by the MCP dependency workflow when
the test fixture enables each language — no pre-install skip markers needed.
"""
from __future__ import annotations

import shutil

import pytest

requires_pyright = pytest.mark.skipif(
    shutil.which("pyright-langserver") is None,
    reason="pyright-langserver not on PATH",
)

requires_uv = pytest.mark.skipif(
    shutil.which("uv") is None,
    reason="uv not on PATH",
)
