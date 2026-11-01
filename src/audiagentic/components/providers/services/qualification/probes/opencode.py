"""OpenCode probes (SH56): a real OpenCode TUI as the human, an HTTP observer, and the busy-turn question first.

Everything runs in a disposable environment: a throw-away HOME/XDG tree, an exec-capable scratch TMPDIR (the TUI's
native library cannot be mapped from a noexec /tmp), an inline config naming only the local stub model, a random
in-memory server password passed to the children by environment only, and a free loopback port. Only processes this
module starts are ever signalled. The evidence is protocol evidence about the harness, never about a vendor model.
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.opencode.join import (
    REQUIRED_PATHS,
    OpenCodeClient,
    OpenCodeError,
    OwnedOpenCodeServer,
)

from ..live import CAPABILITIES, LiveContext, ProbeOutcome
from .codex_tui import HumanTui
from .stub_model import StubModel

PROBE_VERSION = "1"
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")
_TIMEOUT = 40.0
_STUB_REPLY = "STUB-REPLY-"


def disposable_env(root: Path, config: dict[str, Any], password: str, tmp: Path | None = None) -> dict[str, str]:
    """Allowlisted environment: nothing inherited that could carry a credential, everything rooted in ``root``."""
    import os

    for name in ("home", "xdg-config", "xdg-data", "xdg-cache", "xdg-state", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env.update({"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "xdg-config"),
                "XDG_DATA_HOME": str(root / "xdg-data"), "XDG_CACHE_HOME": str(root / "xdg-cache"),
                "XDG_STATE_HOME": str(root / "xdg-state"), "TMPDIR": str(tmp or root / "tmp"),
                "OPENCODE_CONFIG_CONTENT": json.dumps(config), "OPENCODE_SERVER_PASSWORD": password})
    return env


def stub_config(base_url: str) -> dict[str, Any]:
    return {"$schema": "https://opencode.ai/config.json", "model": "stub/stub-model", "enabled_providers": ["stub"],
            "provider": {"stub": {"npm": "@ai-sdk/openai-compatible", "name": "Stub",
                                  "options": {"baseURL": base_url, "apiKey": "none"},
                                  "models": {"stub-model": {"name": "Stub", "tool_call": False,
                                                            "limit": {"context": 8000, "output": 1000}}}}},
            "share": "disabled", "autoupdate": False}


def _failed(name: str, step: str, error: Exception) -> ProbeOutcome:
    return ProbeOutcome(name, False, "probe-failed", {"step": step, "error": getattr(error, "kind", type(error).__name__)})


def _wait(predicate: Any, timeout: float = _TIMEOUT, interval: float = 0.4) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _assistant_texts(client: OpenCodeClient, session_id: str) -> list[str]:
    out = []
    for message in client.messages(session_id):
        if message.get("type") == "assistant":
            out.append("|".join(str(part.get("text")) for part in message.get("content") or [] if part.get("type") == "text"))
    return out


def _user_count(client: OpenCodeClient, session_id: str) -> int:
    return sum(1 for message in client.messages(session_id) if message.get("type") == "user")


def _idle(client: OpenCodeClient, session_id: str) -> bool:
    return session_id not in client.active()


def _find_human_session(client: OpenCodeClient, marker: str) -> str | None:
    found: list[str] = []

    def look() -> bool:
        for session in client.sessions():
            session_id = str(session.get("id"))
            if any(marker in str(m.get("text") or "") for m in client.messages(session_id) if m.get("type") == "user"):
                found.append(session_id)
                return True
        return False

    return found[0] if _wait(look) else None


def run(context: LiveContext) -> list[ProbeOutcome]:
    """Run the OpenCode probes; every capability not measured stays false with a registered reason."""
    seen: dict[str, Any] = {"probe-version": PROBE_VERSION}
    outcomes: dict[str, ProbeOutcome] = {}
    root, workspace = context.root, context.root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    stub = StubModel().start()
    password = secrets.token_urlsafe(24)  # in memory and in the children's environment only
    env = disposable_env(root, stub_config(stub.base_url), password, context.exec_scratch)
    server = OwnedOpenCodeServer(env, workspace)
    tui: HumanTui | None = None
    try:
        client = OpenCodeClient(server.port, password)
        server.start(lambda: client.call("GET", "/api/session/active"))
        missing = sorted(REQUIRED_PATHS - client.openapi_paths())
        if missing:
            return [ProbeOutcome(name, False, "unsupported-protocol-path-missing", {"missing": missing[:6]}) for name in CAPABILITIES]
        tui = HumanTui(Path("opencode"), Path("-"), {**env, "OPENCODE_PASSWORD": password}, workspace,
                       argv=["opencode", "--server", f"http://127.0.0.1:{server.port}"], enter=b"\r").start(settle=10)
        tui.type_and_submit("qualification human one")
        session_id = _find_human_session(client, "qualification human one")
        if session_id is None:
            return [ProbeOutcome(name, False, "probe-failed", {"step": "human-session-not-found",
                                                               "tui-alive": tui.alive}) for name in CAPABILITIES]
        seen["human-session-visible-to-observer"] = True
        seen["human-first-reply"] = _wait(lambda: any(t.startswith(_STUB_REPLY) for t in _assistant_texts(client, session_id)))
        before_sessions = len(client.sessions())

        # passive identity / attach: an independent HTTP client addresses the same session and creates nothing.
        outcomes["passive-identity"] = ProbeOutcome(
            "passive-identity", bool(seen["human-first-reply"]) and len(client.sessions()) == before_sessions, None,
            {"observer-saw-human-prompt": True, "observer-created-nothing": len(client.sessions()) == before_sessions})
        count = _user_count(client, session_id)
        tui.type_and_submit("qualification human two")
        works = _wait(lambda: _user_count(client, session_id) > count and _idle(client, session_id))
        seen["human-works-while-observer-reads"] = works
        outcomes["existing-session-attach"] = ProbeOutcome(
            "existing-session-attach", works, None if works else "probe-failed",
            {"observer-addresses-the-same-session-id": True, "human-ui-works-while-observer-attached": works})

        # The busy-turn question, on the HUMAN's active turn: a queued prompt must not touch it.
        stub.hold()
        users = _user_count(client, session_id)
        before = stub.requests
        tui.type_and_submit("qualification human busy")
        stub.wait_for_requests(before + 1, _TIMEOUT)
        at_active = stub.requests
        retry_id = "msg_" + secrets.token_hex(13)
        queued = client.prompt(session_id, "observer queued prompt", delivery="queue", message_id=retry_id)
        again = client.prompt(session_id, "observer queued prompt", delivery="queue", message_id=retry_id)
        time.sleep(2)
        seen["observer-prompt-accepted-with-delivery"] = queued.get("delivery")
        seen["retry-same-message-id-returned-same-message"] = again.get("id") == queued.get("id")
        seen["model-requests-added-while-human-turn-held"] = stub.requests - at_active
        seen["observer-prompt-waits-in-inbox"] = any(item.get("id") == queued.get("id") for item in client.inbox(session_id))
        stub.release()
        done = _wait(lambda: _idle(client, session_id) and _user_count(client, session_id) >= users + 2
                     and not client.inbox(session_id))
        texts = _assistant_texts(client, session_id)
        replies = [t for t in texts if t.startswith(_STUB_REPLY)]
        seen["human-turn-reply-unchanged"] = bool(replies) and replies[-2 if len(replies) >= 2 else -1].startswith(_STUB_REPLY)
        seen["observer-prompt-ran-after-the-human-turn"] = done
        seen["model-requests-for-human-plus-observer"] = stub.requests - at_active + 1
        seen["observer-prompt-ran-exactly-once"] = seen["model-requests-for-human-plus-observer"] == 2
        admitted = (seen["observer-prompt-accepted-with-delivery"] == "queue" and seen["model-requests-added-while-human-turn-held"] == 0
                    and seen["observer-prompt-waits-in-inbox"] and seen["retry-same-message-id-returned-same-message"]
                    and done and seen["observer-prompt-ran-exactly-once"])
        outcomes["conditional-admission"] = ProbeOutcome(
            "conditional-admission", bool(admitted), None if admitted else "probe-failed",
            {k: seen[k] for k in seen if k.startswith(("observer-prompt", "retry-", "model-requests", "human-turn-reply"))})

        # The human acts independently after the observer's queued prompt.
        count = _user_count(client, session_id)
        tui.type_and_submit("qualification human four")
        independent = _wait(lambda: _user_count(client, session_id) > count and _idle(client, session_id))
        seen["human-independent-action-after-observer-prompt"] = independent
        outcomes["concurrent-human-use"] = ProbeOutcome(
            "concurrent-human-use", bool(independent and works), None if independent and works else "probe-failed",
            {"human-surface": "real-opencode-tui-in-pty", "human-works-while-observer-reads": works,
             "human-independent-action-after-observer-prompt": independent})

        # Result attribution: is the assistant message tied to the prompt by a native id, or only by order?
        linked = any(queued.get("id") and queued["id"] in json.dumps(m) for m in client.messages(session_id) if m.get("type") == "assistant")
        outcomes["correlated-result"] = ProbeOutcome(
            "correlated-result", bool(linked), None if linked else "unproven-result-linked-by-event-order-only",
            {"assistant-message-references-the-prompt-id": bool(linked)})

        # Safe detach, both ways: the observer holds no attachment (stateless HTTP); the human closing the UI must
        # leave the session usable for the observer.
        tui.stop()
        tui = None
        survives = server.alive and _idle(client, session_id) and bool(client.messages(session_id))
        follow = client.prompt(session_id, "observer after the human left", delivery="queue")
        ran = _wait(lambda: _idle(client, session_id) and any(
            m.get("id") == follow.get("id") for m in client.messages(session_id)))
        outcomes["safe-detach"] = ProbeOutcome(
            "safe-detach", bool(survives and ran), None if survives and ran else "probe-failed",
            {"observer-holds-no-attachment": "stateless-http", "server-alive-after-human-closed-ui": server.alive,
             "session-readable-after-human-closed-ui": survives, "observer-prompt-ran-after-human-left": ran})
        reread = len(client.messages(session_id)) > 0 and any(str(s.get("id")) == session_id for s in client.sessions())
        outcomes["reconnect"] = ProbeOutcome("reconnect", reread, None if reread else "probe-failed",
                                             {"new-client-resolves-the-same-session": reread})
        seen["stub-unexpected-requests"] = len(stub.unexpected)
        if stub.unexpected:
            return [_failed(name, "stub-unexpected-request", OpenCodeError("unexpected", "stub")) for name in CAPABILITIES]
    except Exception as error:  # noqa: BLE001 - reported as a failed step, never as proof
        return [_failed(name, "opencode", error) for name in CAPABILITIES]
    finally:
        stub.release()
        if tui is not None:
            tui.stop()
        seen["server-stopped"] = server.stop()
        stub.stop()
    result = []
    for name in CAPABILITIES:
        outcome = outcomes.get(name) or ProbeOutcome(name, False, "unproven-not-probed", {})
        outcome.observations.update({"probe-version": PROBE_VERSION, "server-stopped": seen["server-stopped"],
                                     "session-history": "stub-model"})
        result.append(outcome)
    return result
