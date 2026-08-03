"""Shared isolation fixtures for integration tests."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _fresh_gateway_queue_manager(request: pytest.FixtureRequest):
    """Isolate gateway integration scenarios that share the default profile."""
    if Path(str(request.node.fspath)).parent.name != "agents":
        yield
        return

    from tests.helpers.gateway_queue_isolation import reset_gateway_queue

    reset_gateway_queue()
    yield
