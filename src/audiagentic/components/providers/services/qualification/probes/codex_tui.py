"""Codex human-surface probes (SH54-B): a real Codex TUI in a pseudo-terminal plus an observing client.

The TUI is the actual human-facing Codex interface, started with ``--remote unix://SOCKET`` against the same
disposable app-server the observer uses, with the local stub model configured in the disposable ``CODEX_HOME``.
A "human" prompt is typed into the TUI (kitty-protocol Enter, which the TUI enables) and counted complete
when the observer sees the turn finish. Measured here: that the human's UI keeps working after an observer
attaches and detaches, that an observer's turn completes while the human UI stays attached and the human then
completes an independent action, and what an observer's ``turn/start`` does to a HUMAN's active turn.

Only the TUI process this module starts is ever signalled. Nothing here proves anything about a vendor model.
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import select
import signal
import struct
import termios
import time
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.codex.join import AppServerClient, AppServerError, OwnedAppServer

from ..live import ProbeOutcome
from .stub_model import StubModel

_KITTY_ENTER = b"\x1b[13u"
_TURN_TIMEOUT = 30.0


class HumanTui:
    """One Codex TUI process on a pty, stopped by its exact pid."""

    def __init__(self, executable: Path, socket_path: Path, env: dict[str, str], cwd: Path, *,
                 argv: list[str] | None = None, enter: bytes = _KITTY_ENTER) -> None:
        self._argv = argv or [str(executable), "--remote", f"unix://{socket_path}"]
        self._env, self._cwd, self._enter = env, cwd, enter
        self.pid: int | None = None
        self._fd: int | None = None

    def start(self, settle: float = 8.0) -> HumanTui:
        pid, fd = pty.fork()
        if pid == 0:  # child: become the TUI
            os.chdir(self._cwd)
            os.execvpe(self._argv[0], self._argv, {**self._env, "TERM": "xterm-256color", "LANG": "C.UTF-8"})
        self.pid, self._fd = pid, fd
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))
        self.drain(settle)
        return self

    def drain(self, seconds: float) -> None:
        assert self._fd is not None
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ready, _, _ = select.select([self._fd], [], [], 0.2)
            if ready:
                try:
                    os.read(self._fd, 65536)
                except OSError:
                    return

    def type_and_submit(self, text: str) -> None:
        assert self._fd is not None
        os.write(self._fd, text.encode())
        self.drain(0.7)
        os.write(self._fd, self._enter)

    @property
    def alive(self) -> bool:
        if self.pid is None:
            return False
        try:
            return os.waitpid(self.pid, os.WNOHANG) == (0, 0)
        except ChildProcessError:
            return False

    def stop(self) -> None:
        if self.pid is None:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(self.pid, sig)
            except ProcessLookupError:
                break
            time.sleep(0.8)
            try:
                if os.waitpid(self.pid, os.WNOHANG) != (0, 0):
                    break
            except ChildProcessError:
                break
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
        self.pid = self._fd = None


def _ids(result: dict[str, Any]) -> list[str]:
    return [item if isinstance(item, str) else str(item.get("id")) for item in result.get("data") or []]


async def _turn_count(client: AppServerClient, thread_id: str) -> int:
    try:
        return len((await client.request("thread/turns/list", {"threadId": thread_id})).get("data") or [])
    except AppServerError:
        return -1


async def _idle(client: AppServerClient, thread_id: str) -> bool:
    try:
        thread = (await client.request("thread/read", {"threadId": thread_id})).get("thread") or {}
    except AppServerError:
        return False
    return (thread.get("status") or {}).get("type") == "idle"


async def _human_turn_done(observer: AppServerClient, thread_id: str, before: int) -> bool:
    """The human's prompt produced a new turn that finished (more turns than ``before`` and the thread is idle)."""
    end = time.monotonic() + _TURN_TIMEOUT
    while time.monotonic() < end:
        if await _turn_count(observer, thread_id) > before and await _idle(observer, thread_id):
            return True
        await asyncio.sleep(0.4)
    return False


async def _find_human_thread(observer: AppServerClient, marker: str) -> str | None:
    """The thread whose first prompt is the marker the human typed (never a thread the observer made)."""
    end = time.monotonic() + _TURN_TIMEOUT
    while time.monotonic() < end:
        for thread_id in _ids(await observer.request("thread/loaded/list")):
            try:
                thread = (await observer.request("thread/read", {"threadId": thread_id})).get("thread") or {}
            except AppServerError:
                continue
            if marker in str(thread.get("preview") or ""):
                return thread_id
        await asyncio.sleep(0.4)
    return None


async def probe_human_surface(executable: Path, env: dict[str, str], workspace: Path, root: Path,
                              stub: StubModel) -> dict[str, ProbeOutcome]:
    """Run the human-surface experiment; returns outcomes for the capabilities it can speak to."""
    socket_path = root / "human.sock"
    server = OwnedAppServer(executable, socket_path, env, workspace).start()
    tui: HumanTui | None = None
    clients: list[AppServerClient] = []
    seen: dict[str, Any] = {}

    async def client(name: str) -> AppServerClient:
        connected = await AppServerClient(socket_path, name, timeout=30).connect()
        clients.append(connected)
        await connected.initialize()
        return connected

    try:
        observer = await client("observer")
        tui = HumanTui(executable, socket_path, env, workspace).start()
        tui.type_and_submit("qualification human one")
        thread_id = await _find_human_thread(observer, "qualification human one")
        if thread_id is None:
            return {"concurrent-human-use": ProbeOutcome("concurrent-human-use", False, "probe-failed",
                                                         {"step": "human-thread-not-found"})}
        seen["human-thread-visible-to-observer"] = True
        base = await _turn_count(observer, thread_id)
        seen["human-first-turn-completed"] = await _human_turn_done(observer, thread_id, base - 1)

        # Attach, then detach: the human's UI must keep working through both.
        await observer.request("thread/resume", {"threadId": thread_id})
        count = await _turn_count(observer, thread_id)
        tui.type_and_submit("qualification human two")
        seen["human-works-while-observer-attached"] = await _human_turn_done(observer, thread_id, count)
        await observer.request("thread/unsubscribe", {"threadId": thread_id})
        count = await _turn_count(observer, thread_id)
        tui.type_and_submit("qualification human three")
        seen["human-works-after-observer-detached"] = await _human_turn_done(observer, thread_id, count)

        # The observer takes an idle turn while the human UI stays attached; the human then acts independently.
        await observer.request("thread/resume", {"threadId": thread_id})
        count = await _turn_count(observer, thread_id)
        mine = (await observer.request("turn/start", {"threadId": thread_id, "input": [
            {"type": "text", "text": "observer turn"}], "clientUserMessageId": "qualify-human-B"}))["turn"]["id"]
        done = await observer.wait_for("turn/completed", _TURN_TIMEOUT,
                                       match=lambda p: (p.get("turn") or {}).get("id") == mine)
        seen["observer-idle-turn-completed"] = done is not None
        count = await _turn_count(observer, thread_id)
        tui.type_and_submit("qualification human four")
        seen["human-independent-action-after-observer-turn"] = await _human_turn_done(observer, thread_id, count)

        # The decisive case: the observer starts a turn while the HUMAN's turn is active.
        stub.hold()
        count = await _turn_count(observer, thread_id)
        observer.notifications.clear()  # only notifications from the human's new turn may identify it
        before_human = stub.requests
        tui.type_and_submit("qualification human busy")
        started = await observer.wait_for("turn/started", _TURN_TIMEOUT)
        human_turn = ((started or {}).get("params") or {}).get("turn", {}).get("id")
        stub.wait_for_requests(before_human + 1, _TURN_TIMEOUT)  # the human's turn is now held open at the model
        requests_at_active = stub.requests
        reply = await observer.request("turn/start", {"threadId": thread_id, "input": [
            {"type": "text", "text": "observer injects into the human turn"}], "clientUserMessageId": "qualify-human-busy-B"})
        returned = reply["turn"]["id"]
        await asyncio.sleep(1.5)
        seen["human-turn-id-observed"] = bool(human_turn)
        # None (not False) when the human's turn id could not be observed: that is unmeasured, not "no steer".
        seen["observer-turn-start-returned-the-human-turn-id"] = (returned == human_turn) if human_turn else None
        seen["model-requests-added-by-the-observer-start"] = stub.requests - requests_at_active
        stub.release()
        seen["human-turn-completed-after-release"] = await _human_turn_done(observer, thread_id, count)
        seen["tui-alive-at-end"] = tui.alive
        seen["stub-unexpected-requests"] = len(stub.unexpected)
    except Exception as error:  # noqa: BLE001 - reported as a failed step, never as proof
        return {"concurrent-human-use": ProbeOutcome(
            "concurrent-human-use", False, "probe-failed",
            {"step": "human-surface", "error": getattr(error, "kind", type(error).__name__), **seen})}
    finally:
        stub.release()
        for connected in clients:
            try:
                await connected.close()
            except Exception:  # noqa: BLE001, S110 - closing a dead client must not hide the result
                pass
        if tui is not None:
            tui.stop()
        seen["server-stopped"] = server.stop()

    ok = (seen.get("human-works-while-observer-attached") and seen.get("human-works-after-observer-detached")
          and seen.get("observer-idle-turn-completed") and seen.get("human-independent-action-after-observer-turn")
          and not seen.get("stub-unexpected-requests"))
    seen["human-surface"] = "real-codex-tui-in-pty"
    return {"concurrent-human-use": ProbeOutcome("concurrent-human-use", bool(ok), None if ok else "probe-failed", seen)}
