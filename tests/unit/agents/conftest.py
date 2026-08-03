"""Shared fixtures for agents unit tests.

agents_gateway_api._QUEUE_MANAGER is a process-global singleton (by design —
one instance per hosting process, see its module docstring). Left un-reset,
two tests using the same agent_profile_id (most fixtures default to
"default") share the same in-memory _ProfileQueue, so a worker thread
started by one test's project_root can dequeue and process a request
belonging to a later test's (different) project_root — a real cross-test
leak, not a production concern (a real process only ever has one project_root).
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fresh_gateway_queue_manager():
    from tests.helpers.gateway_queue_isolation import reset_gateway_queue

    reset_gateway_queue()
    yield
