"""A GPT-wide limit holds new work, refreshes a limited tab periodically and lifts on progress."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway.queue.queue import GatewayQueueManager
from audiagentic.components.providers.adapters.gpt_auto.runtime import (
    GptAutoProviderRuntime,
    _RateLimitTab,
)
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


def _tab(url="https://chatgpt.com/c/a", *, limited=False, loaded=False, generating=False):
    return _RateLimitTab(handle=url[-1], url=url, limited=limited, loaded=loaded, generating=generating)


def _runtime(scans, *, probes=(), confirm=True):
    """A watcher host fed one scripted scan per tick; it stops itself when the script ends."""
    calls = {"reload": 0, "probe": 0, "confirm": 0}
    bridge = object()
    ns = SimpleNamespace(
        _bridge=bridge, RATE_LIMIT_SOURCE_ID="chatgpt",
        config=SimpleNamespace(browser=SimpleNamespace(rate_limit_check_interval_seconds=0.01,
                                                       rate_limit_refresh_interval_seconds=0.03)),
    )
    results, probe_results = iter(scans), iter(probes)

    async def scan():
        try:
            return next(results)
        except StopIteration:
            ns._bridge = None
            return []

    async def reload(_tab):
        calls["reload"] += 1

    async def probe(_url):
        calls["probe"] += 1
        return next(probe_results, False)

    async def confirm_limit(_tabs):
        calls["confirm"] += 1
        return confirm

    ns._scan_rate_limit, ns._reload_limited_tab, ns._probe_chat_url = scan, reload, probe
    ns._confirm_limit = confirm_limit
    return ns, bridge, calls


def _run(ns, bridge):
    asyncio.run(GptAutoProviderRuntime._watch_rate_limit(ns, bridge))


def test_detection_holds_and_the_hold_stays_while_the_page_is_shown() -> None:
    ns, bridge, calls = _runtime([[_tab(limited=True)]] * 6)
    _run(ns, bridge)
    held = get_admission_holds().get("chatgpt")
    assert held is not None and held.reason == "rate-limited"
    assert calls["reload"] >= 1  # a limited tab is reloaded while held


def test_a_limited_tab_that_loads_normally_lifts_the_hold() -> None:
    ns, bridge, _calls = _runtime([[_tab(limited=True)]] * 2 + [[_tab(loaded=True)]])
    _run(ns, bridge)
    assert get_admission_holds().get("chatgpt") is None


def test_a_generating_turn_lifts_the_hold_even_while_another_tab_is_limited() -> None:
    ns, bridge, _calls = _runtime([[_tab(limited=True)], [_tab(limited=True), _tab("https://chatgpt.com/c/b", generating=True)]])
    _run(ns, bridge)
    assert get_admission_holds().get("chatgpt") is None


def test_the_limited_tab_vanishing_does_not_lift_the_hold() -> None:
    ns, bridge, calls = _runtime([[_tab(limited=True)]] * 2 + [[]] * 6)
    _run(ns, bridge)
    assert get_admission_holds().get("chatgpt") is not None  # no proof of recovery
    assert calls["probe"] >= 1  # so the remembered chat is reopened to find out


def test_a_probe_that_loads_lifts_the_hold_after_the_tab_vanished() -> None:
    ns, bridge, calls = _runtime([[_tab(limited=True)]] * 2 + [[]] * 8, probes=[False, True])
    _run(ns, bridge)
    assert calls["probe"] == 2 and get_admission_holds().get("chatgpt") is None


def test_an_unrelated_loaded_tab_is_not_proof_the_limit_is_over() -> None:
    ns, bridge, _calls = _runtime([[_tab(limited=True)]] * 2 + [[_tab("https://chatgpt.com/c/other", loaded=True)]] * 2)
    _run(ns, bridge)
    assert get_admission_holds().get("chatgpt") is not None


def test_no_limit_page_means_no_hold() -> None:
    ns, bridge, _calls = _runtime([[_tab(loaded=True)]] * 3)
    _run(ns, bridge)
    assert get_admission_holds().get("chatgpt") is None


def test_a_stale_limit_page_that_reloads_normally_does_not_hold_and_is_not_rechecked_every_tick() -> None:
    ns, bridge, calls = _runtime([[_tab(limited=True)], [_tab(loaded=True)], [_tab(loaded=True)]], confirm=False)
    _run(ns, bridge)
    assert get_admission_holds().get("chatgpt") is None
    assert calls["confirm"] == 1


def test_a_limit_page_that_survives_a_reload_holds() -> None:
    ns, bridge, calls = _runtime([[_tab(limited=True)]] * 3, confirm=True)
    _run(ns, bridge)
    assert get_admission_holds().get("chatgpt") is not None and calls["confirm"] == 1
