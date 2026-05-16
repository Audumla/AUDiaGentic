from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("AUDIAGENTIC_DOCKER_TESTS") == "1":
        return
    skip = pytest.mark.skip(
        reason="release integration tests write files — run inside Docker; set AUDIAGENTIC_DOCKER_TESTS=1 to override"
    )
    for item in items:
        if "tests/integration/release" in item.nodeid.replace("\\", "/"):
            item.add_marker(skip)
