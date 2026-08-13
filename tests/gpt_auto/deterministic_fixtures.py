"""Reusable, non-live fixtures for the GPT-auto deterministic ladder.

These fakes model external facts only.  They deliberately do not contain any
provider, page-selection, recovery, or gateway policy logic.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Awaitable, Callable
from typing import Any


class NetworkTripwire:
    """A callable network boundary that fails on any unexpected use."""

    def __init__(self) -> None:
        self.attempts: list[tuple[str, tuple[Any, ...]]] = []

    def fail(self, operation: str) -> Callable[..., Any]:
        def _blocked(*args: Any, **_kwargs: Any) -> Any:
            self.attempts.append((operation, args))
            raise AssertionError(f"deterministic test attempted network operation: {operation}")

        return _blocked

    def patch_socket(self, monkeypatch: Any) -> None:
        monkeypatch.setattr(socket, "create_connection", self.fail("socket.create_connection"))
        monkeypatch.setattr(socket.socket, "connect", self.fail("socket.connect"))


class ProcessTripwire:
    """A fake process launcher which records and rejects launches."""

    def __init__(self) -> None:
        self.attempts: list[tuple[Any, ...]] = []

    def __call__(self, *args: Any, **_kwargs: Any) -> Any:
        self.attempts.append(args)
        raise AssertionError("deterministic test attempted a browser/provider process launch")


class Gate:
    """Deterministic async barrier; tests control release explicitly."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def wait(self) -> None:
        self.entered.set()
        await self.release.wait()


class ScriptedCdpClient:
    """CDP command/event fake with explicit per-method scripts."""

    def __init__(self) -> None:
        self.events: asyncio.Queue[Any] = asyncio.Queue()
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []
        self.scripts: dict[str, list[Any]] = {}

    def script(self, method: str, *results: Any) -> None:
        self.scripts[method] = list(results)

    async def command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        del timeout
        payload = dict(params or {})
        self.calls.append((method, payload, session_id))
        scripted = self.scripts.get(method)
        if not scripted:
            return {}
        result = scripted.pop(0)
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            result = result(method, payload, session_id)
        if isinstance(result, Awaitable):
            result = await result
        return result


class SnapshotScript:
    """Finite snapshot sequence; exhaustion is a test failure, not a guess."""

    def __init__(self, *snapshots: dict[str, Any]) -> None:
        self._snapshots = list(snapshots)
        self.index = 0

    def next(self) -> dict[str, Any]:
        if self.index >= len(self._snapshots):
            raise AssertionError("snapshot script exhausted")
        snapshot = self._snapshots[self.index]
        self.index += 1
        return dict(snapshot)


class RecordingBindingSink:
    def __init__(self) -> None:
        self.updates: list[Any] = []

    async def __call__(self, update: Any) -> None:
        self.updates.append(update)


class FakeTargetTable:
    def __init__(self, *targets: dict[str, Any]) -> None:
        self.targets: dict[str, dict[str, Any]] = {
            str(target["targetId"]): dict(target) for target in targets
        }

    def as_infos(self) -> list[dict[str, Any]]:
        return [dict(target) for target in self.targets.values()]

    def add(self, **target: Any) -> None:
        self.targets[str(target["targetId"])] = dict(target)

    def remove(self, target_id: str) -> None:
        self.targets.pop(target_id, None)
