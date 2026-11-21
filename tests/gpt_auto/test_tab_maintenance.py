"""The idle-tab reaper must start without a request, and only ever attach to a browser that is already up."""
from __future__ import annotations

import asyncio
from pathlib import Path

from audiagentic.components.providers.adapters.gpt_auto import tab_maintenance


class _Runtime:
    def __init__(self, up: bool) -> None:
        self.up = up
        self.attached = 0

    async def connect_existing(self) -> bool:
        self.attached += 1
        return self.up


def _patch(monkeypatch, runtime: _Runtime, seen: list) -> None:
    monkeypatch.setattr(tab_maintenance, "_provider_settings", lambda root, pid: {})
    monkeypatch.setattr(tab_maintenance.GptAutoConfig, "from_project_dict", classmethod(lambda cls, d: object()))
    monkeypatch.setattr(tab_maintenance, "get_runtime", lambda root, cfg: seen.append(root) or runtime)


def test_attaches_through_the_first_resolvable_project(monkeypatch) -> None:
    runtime, seen = _Runtime(True), []
    _patch(monkeypatch, runtime, seen)
    assert asyncio.run(tab_maintenance.attach_for_tab_maintenance([Path("/p1"), Path("/p2")])) is True
    assert runtime.attached == 1 and seen == [Path("/p1")]


def test_reports_no_browser_without_launching_one(monkeypatch) -> None:
    runtime, seen = _Runtime(False), []
    _patch(monkeypatch, runtime, seen)
    assert asyncio.run(tab_maintenance.attach_for_tab_maintenance([Path("/p1")])) is False


def test_an_unreadable_project_is_skipped_and_no_projects_is_a_no_op(monkeypatch) -> None:
    runtime, seen = _Runtime(True), []
    _patch(monkeypatch, runtime, seen)
    calls = iter([RuntimeError("bad config"), {}])

    def settings(root, pid):
        value = next(calls)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(tab_maintenance, "_provider_settings", settings)
    assert asyncio.run(tab_maintenance.attach_for_tab_maintenance([Path("/bad"), Path("/good")])) is True
    assert seen == [Path("/good")]
    assert asyncio.run(tab_maintenance.attach_for_tab_maintenance([])) is False
