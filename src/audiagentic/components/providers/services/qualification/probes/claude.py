"""Claude Code probes (SH55): what can an outside caller see of, or send to, a running interactive session?

A real Claude Code TUI runs in a pseudo-terminal in a disposable environment: a throw-away HOME, a fake API key that
only the local stub model accepts, ``--bare`` (no hooks, memory or CLAUDE.md discovery), an exec-capable TMPDIR and a
pre-seeded config that skips onboarding. The only native outside view is ``claude agents --json``. The probe proves
that this listing identifies the running session without touching it, and records that no native route sends a
prompt to it. That negative finding was established on the reviewed versions below; any other version leaves every
capability unproven rather than inheriting it. Channels are not probed: they are unavailable to API-key sessions
(measured), so channel delivery stays unmeasured. Only processes this module starts are ever signalled.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.claude.join import list_sessions

from ..live import CAPABILITIES, LiveContext, ProbeOutcome
from .codex_tui import HumanTui
from .env import disposable_env as shared_env
from .stub_model import StubModel

PROBE_VERSION = "2"
#: Versions whose native surfaces were inspected for a way to send into a running interactive session.
REVIEWED_VERSIONS = ("2.1.316",)
NO_ENDPOINT = "unsupported-no-existing-session-endpoint"
UNREVIEWED = "unproven-version-not-reviewed"
_KEY = "sk-ant-api03-" + "stub" * 12  # accepted by nothing but the local stub
_TIMEOUT = 40.0
_KINDS = ("interactive", "background")
_IDLE = "idle"
_BUSY = ("busy", "running", "working", "active")


def disposable_env(root: Path, stub: StubModel, tmp: Path | None = None) -> dict[str, str]:
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    env = shared_env(root, tmp=tmp, extra={
        "ANTHROPIC_API_KEY": _KEY, "ANTHROPIC_BASE_URL": stub.root_url, "DISABLE_TELEMETRY": "1",
        "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    (root / "home" / ".claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True, "theme": "dark", "numStartups": 5,
        "customApiKeyResponses": {"approved": [_KEY[-20:]], "rejected": []},
        "projects": {str(workspace): {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True}}}))
    return env


class _Clock:
    """One overall deadline for the whole probe; every wait and listing is bounded by what remains."""

    def __init__(self, seconds: float) -> None:
        self._end = time.monotonic() + seconds

    def remaining(self) -> float:
        return max(0.0, self._end - time.monotonic())

    def wait(self, predicate: Any, timeout: float = _TIMEOUT, interval: float = 0.5) -> bool:
        end = time.monotonic() + min(timeout, self.remaining())
        while time.monotonic() < end:
            if predicate():
                return True
            time.sleep(interval)
        return False


class _Observer:
    """Reads the running session through ``claude agents --json``; every value it returns is from a finite set."""

    def __init__(self, env: dict[str, str], workspace: Path, pid: int | None) -> None:
        self._env, self._workspace, self.pid = env, workspace, pid

    def entry(self) -> dict[str, Any] | None:
        return next((item for item in list_sessions(self._env, self._workspace) or [] if item.get("pid") == self.pid), None)

    def status(self) -> str | None:
        entry = self.entry()
        if entry is None:
            return None
        value = entry.get("status")
        return value if value == _IDLE or value in _BUSY else "other"

    def listed(self) -> tuple[bool, str | None]:
        entry = self.entry()
        session_id = entry.get("sessionId") if entry else None
        return isinstance(session_id, str) and bool(session_id), session_id if isinstance(session_id, str) else None

    def count(self) -> int:
        return len(list_sessions(self._env, self._workspace) or [])


def _transcript_has(home: Path, marker: str) -> bool:
    """True when the session's own transcript records the stub's reply (a completed model turn, not just idle)."""
    return any(marker in path.read_text(errors="replace") for path in (home / ".claude" / "projects").glob("*/*.jsonl"))


def _failed(step: str) -> list[ProbeOutcome]:
    return [ProbeOutcome(name, False, "probe-failed", {"step": step}) for name in CAPABILITIES]


def run(context: LiveContext) -> list[ProbeOutcome]:
    root, workspace, clock = context.root, context.root / "workspace", _Clock(240)
    version = str(context.facts.get("executable-version") or "")
    reviewed = any(version == known or version.startswith(known + " ") for known in REVIEWED_VERSIONS)
    stub = StubModel().start()
    tui: HumanTui | None = None
    try:
        env = disposable_env(root, stub, context.exec_scratch)
        tui = HumanTui(Path("claude"), Path("-"), env, workspace,
                       argv=["claude", "--bare", "--model", "stub-model"], enter=b"\r").start(settle=12)
        observer = _Observer(env, workspace, tui.pid)
        tui.type_and_submit("qualification human one")
        if not stub.wait_for_requests(1, min(_TIMEOUT, clock.remaining())):
            return _failed("model-request-never-arrived")
        replied = clock.wait(lambda: _transcript_has(root / "home", "STUB-REPLY-1"))
        idle = clock.wait(lambda: observer.status() == _IDLE)
        listed, session_id = observer.listed()
        before = observer.count()
        created_nothing = observer.count() == before
        stable = observer.listed()[1] == session_id and session_id is not None

        # The human's second turn is held open at the model: the listing must report it busy, the observer must add
        # nothing to it, and the turn must then complete on its own.
        stub.hold()
        requests = stub.requests
        tui.type_and_submit("qualification human busy")
        arrived = stub.wait_for_requests(requests + 1, min(_TIMEOUT, clock.remaining()))
        busy = arrived and clock.wait(lambda: observer.status() in _BUSY, 20)
        time.sleep(1)
        added = stub.requests - (requests + 1)
        stub.release()
        finished = clock.wait(lambda: observer.status() == _IDLE and _transcript_has(root / "home", "STUB-REPLY-2"))
        stub_clean = not stub.unexpected
        kind = (observer.entry() or {}).get("kind")
    except Exception as error:  # noqa: BLE001 - a failed step proves nothing
        return [ProbeOutcome(name, False, "probe-failed", {"error": type(error).__name__}) for name in CAPABILITIES]
    finally:
        stub.release()
        if tui is not None:
            tui.stop()
        stub.stop()
    if not stub_clean:
        return _failed("stub-unexpected-request")
    shared = {"probe-version": PROBE_VERSION, "executable-version-reviewed": reviewed, "channels": "unavailable-to-api-key-sessions",
              "kind": kind if kind in _KINDS else "other"}
    identity = bool(listed and idle and replied and created_nothing and stable)
    outcomes = {
        "passive-identity": ProbeOutcome("passive-identity", identity, None if identity else "probe-failed", {
            "agents-json-lists-the-running-session": listed, "session-id-stable-across-listings": stable,
            "observer-created-nothing": created_nothing, "human-turn-completed-in-transcript": replied, **shared}),
        "reconnect": ProbeOutcome("reconnect", False, "unproven-no-attachment-to-reconnect", {
            "a-new-listing-resolves-the-same-session-id": stable, **shared}),
        "concurrent-human-use": ProbeOutcome("concurrent-human-use", False, "unproven-no-observer-action-to-coexist-with", {
            "human-surface": "real-claude-code-tui-in-pty", "listing-reported-busy-during-held-turn": bool(busy),
            "observer-added-model-requests": added, "held-turn-completed-in-transcript": finished, **shared}),
    }
    for name in ("existing-session-attach", "conditional-admission", "correlated-result", "safe-detach"):
        reason = ("unproven-no-attachment-to-detach" if name == "safe-detach" else NO_ENDPOINT) if reviewed else UNREVIEWED
        outcomes[name] = ProbeOutcome(name, False, reason, {
            "native-routes-that-send-to-a-running-interactive-session": 0, "listing-is-read-only": True, **shared})
    if not (busy and finished and added == 0):
        return [ProbeOutcome(name, False, "probe-failed", {"step": "held-turn-not-observed", **shared}) for name in CAPABILITIES]
    return [outcomes[name] for name in CAPABILITIES]
