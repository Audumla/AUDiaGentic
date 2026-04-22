"""Test isolation fixtures for planning integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_event_bus_subscriptions():
    """Isolate EventBus state for each planning integration test.

    Two problems this solves:

    1. Subscription accumulation: each test creates a new PlanningAPI (unique tmp_path),
       which registers propagation and knowledge subscriptions on the singleton EventBus.
       Without cleanup, by test N there are N handlers firing per state change — O(N)
       fanout that caused 56-72 second archive test times.

    2. Real project pollution: on_planning_state_change uses Path.cwd() (the real project
       root), writing test events to the actual event journal and event-state.yml. Blocking
       the knowledge subscription in tests prevents this side-effect and eliminates ~1s of
       disk I/O per state() call (load YAML config + read/write event state).

    Setup (pre-yield): set knowledge sentinel so setup_event_subscriptions() is a no-op
    during this test — PlanningAPI.__init__ won't register a knowledge handler.

    Teardown (post-yield): clear all bus subscriptions and reset all module-level handles
    so the next test starts clean.

    Pytest runs autouse fixtures before named fixtures of the same scope, so the sentinel
    is in place before planning_root creates PlanningAPI.
    """
    # Block knowledge subscription from registering for this test.
    # Uses a sentinel object (truthy, non-None) so setup_event_subscriptions() early-returns.
    _sentinel = object()
    try:
        import audiagentic.knowledge as _knowledge
        _knowledge._knowledge_subscription_handle = _sentinel
    except Exception:
        pass

    yield

    # Clear all bus subscriptions accumulated during this test.
    try:
        from audiagentic.interoperability import get_bus
        bus = get_bus()
        with bus._subscription_lock:
            bus._subscriptions.clear()
    except Exception:
        pass

    # Reset knowledge handle so next test (or prod code) can re-subscribe cleanly.
    try:
        import audiagentic.knowledge as _knowledge
        _knowledge._knowledge_subscription_handle = None
    except Exception:
        pass

    # Reset propagation registry so next test's PlanningAPI registers fresh.
    try:
        import audiagentic.planning.app.api as _api
        _api._propagation_subscriptions.clear()
    except Exception:
        pass
