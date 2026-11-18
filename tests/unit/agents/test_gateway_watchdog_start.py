"""The dispatch watchdog starts even when the managed launch gives no explicit service root."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from audiagentic.components.agents.gateway.service import host as host_mod


def test_watchdog_starts_with_the_store_root_when_no_service_root_is_given(tmp_path, monkeypatch):
    seen: dict[str, object] = {}
    started = threading.Event()

    def fake_run_watchdog(service_root, health, stop, **kwargs):
        seen["root"] = service_root
        started.set()

    monkeypatch.setattr("audiagentic.components.agents.gateway.stuck.run_watchdog", fake_run_watchdog)
    fake = SimpleNamespace(
        _application=object(),
        _service_root=None,
        service_store=SimpleNamespace(root=Path(tmp_path)),
        _watchdog_thread=None,
        _watchdog_stop=threading.Event(),
    )

    host_mod.GatewayServiceHost._start_dispatch_watchdog(fake)

    assert started.wait(5)
    assert seen["root"] == Path(tmp_path)
    assert fake._watchdog_thread is not None
