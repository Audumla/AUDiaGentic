"""Claude Code probes (SH55): what can an outside caller see of, or send to, a running interactive session?

A real Claude Code TUI runs in a pseudo-terminal in a disposable environment: a throw-away HOME/XDG tree, a fake
API key that only the local stub model accepts, ``--bare`` (no hooks, memory or CLAUDE.md discovery), an exec-capable
TMPDIR and a pre-seeded config that skips onboarding. The only native outside view is ``claude agents --json``; the
probe measures it while a human turn is idle and while it is held busy, and records that no native route sends a
prompt to the running session. Channels are not probed: they are unavailable to API-key sessions (measured), so
channel delivery stays unmeasured, never assumed. Only processes this module starts are ever signalled.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.claude.join import list_sessions

from ..live import CAPABILITIES, LiveContext, ProbeOutcome
from .codex_tui import HumanTui
from .stub_model import StubModel

PROBE_VERSION = "1"
NO_ENDPOINT = "unsupported-no-existing-session-endpoint"
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
_KEY = "sk-ant-api03-" + "stub" * 12  # accepted by nothing but the local stub
_TIMEOUT = 40.0


def disposable_env(root: Path, stub: StubModel, tmp: Path | None = None) -> dict[str, str]:
    for name in ("home", "xdg-config", "xdg-data", "xdg-cache", "xdg-state", "tmp", "workspace"):
        (root / name).mkdir(parents=True, exist_ok=True)
    workspace = root / "workspace"
    (root / "home" / ".claude.json").write_text(json.dumps({
        "hasCompletedOnboarding": True, "theme": "dark", "numStartups": 5,
        "customApiKeyResponses": {"approved": [_KEY[-20:]], "rejected": []},
        "projects": {str(workspace): {"hasTrustDialogAccepted": True, "hasCompletedProjectOnboarding": True}}}))
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env.update({"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "xdg-config"),
                "XDG_DATA_HOME": str(root / "xdg-data"), "XDG_CACHE_HOME": str(root / "xdg-cache"),
                "XDG_STATE_HOME": str(root / "xdg-state"), "TMPDIR": str(tmp or root / "tmp"),
                "ANTHROPIC_API_KEY": _KEY, "ANTHROPIC_BASE_URL": stub.root_url, "DISABLE_TELEMETRY": "1",
                "DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    return env


def _wait(predicate: Any, timeout: float = _TIMEOUT, interval: float = 0.5) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _entry(env: dict[str, str], workspace: Path, pid: int | None) -> dict[str, Any] | None:
    for item in list_sessions(env, workspace) or []:
        if item.get("pid") == pid:
            return item
    return None


def run(context: LiveContext) -> list[ProbeOutcome]:
    root, workspace = context.root, context.root / "workspace"
    stub = StubModel().start()
    tui: HumanTui | None = None
    seen: dict[str, Any] = {"probe-version": PROBE_VERSION, "channels": "unavailable-to-api-key-sessions"}
    outcomes: dict[str, ProbeOutcome] = {}
    try:
        env = disposable_env(root, stub, context.exec_scratch)
        tui = HumanTui(Path("claude"), Path("-"), env, workspace,
                       argv=["claude", "--bare", "--model", "stub-model"], enter=b"\r").start(settle=12)
        tui.type_and_submit("qualification human one")
        stub.wait_for_requests(1, _TIMEOUT)
        idle = _wait(lambda: (_entry(env, workspace, tui.pid) or {}).get("status") == "idle")
        entry = _entry(env, workspace, tui.pid)
        listed = entry is not None and bool(entry.get("sessionId"))
        seen.update({"listed-by-agents-json": listed, "kind": (entry or {}).get("kind"), "idle-status-observed": idle})
        session_id = (entry or {}).get("sessionId")
        count_before = len(list_sessions(env, workspace) or [])
        again = _entry(env, workspace, tui.pid)
        stable = bool(again and again.get("sessionId") == session_id)
        created_nothing = len(list_sessions(env, workspace) or []) == count_before

        # The human's turn is held busy: the listing must say so, the turn must stay untouched, and nothing the
        # observer can do natively reaches the running session.
        stub.hold()
        before = stub.requests
        tui.type_and_submit("qualification human busy")
        stub.wait_for_requests(before + 1, _TIMEOUT)
        busy = _wait(lambda: (_entry(env, workspace, tui.pid) or {}).get("status") not in (None, "idle"), 20)
        seen["busy-status-while-turn-held"] = (_entry(env, workspace, tui.pid) or {}).get("status")
        time.sleep(2)
        seen["model-requests-added-by-observer"] = stub.requests - (before + 1)
        stub.release()
        done = _wait(lambda: (_entry(env, workspace, tui.pid) or {}).get("status") == "idle")
        seen["human-turn-completed-after-observer-polls"] = done
        survives = bool(tui.alive and done)

        outcomes["passive-identity"] = ProbeOutcome("passive-identity", bool(listed and created_nothing), None if listed else "probe-failed",
                                                    {"agents-json-lists-the-running-session": listed, "observer-created-nothing": created_nothing})
        outcomes["reconnect"] = ProbeOutcome("reconnect", stable, None if stable else "probe-failed",
                                             {"a-new-listing-resolves-the-same-session-id": stable})
        outcomes["concurrent-human-use"] = ProbeOutcome(
            "concurrent-human-use", survives and busy, None if survives and busy else "probe-failed",
            {"human-surface": "real-claude-code-tui-in-pty", "status-reflects-busy-turn": busy,
             "human-turn-completed-after-observer-polls": done, "observer-sent-nothing": True})
        for name in ("existing-session-attach", "conditional-admission", "correlated-result", "safe-detach"):
            reason = "unproven-no-attachment-to-detach" if name == "safe-detach" else NO_ENDPOINT
            outcomes[name] = ProbeOutcome(name, False, reason, {
                "native-routes-that-send-to-a-running-interactive-session": 0,
                "listing-is-read-only": True, "attach-and-logs-address-background-sessions-only": True})
        if stub.unexpected:
            return [ProbeOutcome(name, False, "probe-failed", {"step": "stub-unexpected-request"}) for name in CAPABILITIES]
    except Exception as error:  # noqa: BLE001 - a failed step proves nothing
        return [ProbeOutcome(name, False, "probe-failed", {"error": type(error).__name__}) for name in CAPABILITIES]
    finally:
        stub.release()
        if tui is not None:
            tui.stop()
        stub.stop()
    return [_with(outcomes.get(name) or ProbeOutcome(name, False, "unproven-not-probed", {}), seen) for name in CAPABILITIES]


def _with(outcome: ProbeOutcome, seen: dict[str, Any]) -> ProbeOutcome:
    outcome.observations.update(seen)
    return outcome
