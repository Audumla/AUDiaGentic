"""E2E CLI fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def project_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Module-scoped temporary directory used as the project root for MCP server tests."""
    return tmp_path_factory.mktemp("e2e-cli-project")
