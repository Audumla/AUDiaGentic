"""A GPT-wide limit holds new work, refreshes a limited tab periodically and lifts on progress."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway.queue.queue import GatewayQueueManager
from audiagentic.components.providers.adapters.gpt_auto.runtime import GptAutoProviderRuntime
from audiagentic.foundation.system.admission_holds import AdmissionHolds, get_admission_holds


@pytest.fixture(autouse=True)
def _clean_holds():
    get_admission_holds().lift("chatgpt")
    yield
    get_admission_holds().lift("chatgpt")


def test_holds_are_per_source_and_lifting_notifies_listeners_once() -> None:
    holds, lifted = AdmissionHolds(), []

    class Owner:
        def on_lift(self, source_id: str) -> None:
            lifted.append(source_id)

    owner = Owner()
    holds.on_lift(owner.on_lift)
    assert holds.hold("chatgpt", "rate-limited") is True and holds.hold("chatgpt", "rate-limited") is False
    assert holds.get("other") is None and holds.get("chatgpt").reason == "rate-limited"
    assert holds.lift("chatgpt") is True and holds.lift("chatgpt") is False
    assert lifted == ["chatgpt"]


def _entry(sources, pinned=None):
    return SimpleNamespace(instance_facts=[SimpleNamespace(source_id=s) for s in sources], session_source_id=pinned)


def test_the_queue_keeps_requests_for_a_held_source_and_not_others() -> None:
    held = GatewayQueueManager._admission_held
    assert held(_entry(["chatgpt"])) is False
    get_admission_holds().hold("chatgpt", "rate-limited")
    assert held(_entry(["chatgpt"])) is True
    assert held(_entry(["other"])) is False
    assert held(_entry(["chatgpt", "other"])) is False  # a free source can still run it
    assert held(_entry(["chatgpt", "other"], pinned="chatgpt")) is True  # a session bound to the held source waits


def _runtime(scans):
    calls = {"reload": 0}
    bridge = object()
    ns = SimpleNamespace(
        _bridge=bridge, RATE_LIMIT_SOURCE_ID="chatgpt",
        config=SimpleNamespace(browser=SimpleNamespace(rate_limit_check_interval_seconds=0.01,
                                                       rate_limit_refresh_interval_seconds=0.05)),
    )
    results = iter(scans)

    async def scan():
        try:
            value = next(results)
        except StopIteration:
            ns._bridge = None
            return ([], False)
        return value

    async def reload():
        calls["reload"] += 1

    ns._scan_rate_limit, ns._reload_one_limited_tab = scan, reload
    return ns, bridge, calls


def test_detecting_the_limit_holds_then_refreshes_then_lifts_when_a_tab_loads() -> None:
    page = object()
    ns, bridge, calls = _runtime([([page], False)] * 12 + [([], False)])

    asyncio.run(GptAutoProviderRuntime._watch_rate_limit(ns, bridge))
    assert calls["reload"] >= 1  # a limited tab was reloaded while held
    assert get_admission_holds().get("chatgpt") is None  # and lifted once a tab loaded again


def test_progress_on_a_running_turn_lifts_the_hold_even_while_a_tab_is_limited() -> None:
    page = object()
    ns, bridge, _calls = _runtime([([page], False), ([page], True)])
    asyncio.run(GptAutoProviderRuntime._watch_rate_limit(ns, bridge))
    assert get_admission_holds().get("chatgpt") is None


def test_the_hold_stays_while_the_limit_page_is_shown() -> None:
    page = object()
    ns, bridge, calls = _runtime([([page], False)] * 3)
    seen = []

    async def run():
        task = asyncio.create_task(GptAutoProviderRuntime._watch_rate_limit(ns, bridge))
        await asyncio.sleep(0.025)
        seen.append(get_admission_holds().get("chatgpt"))
        await task

    asyncio.run(run())
    assert seen[0] is not None and seen[0].reason == "rate-limited"
