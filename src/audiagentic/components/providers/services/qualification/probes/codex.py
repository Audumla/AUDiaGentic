"""Codex app-server native probes (SH54-A): identity, attach, detach and reconnect over the real protocol.

Each probe talks to a DISPOSABLE ``codex app-server --listen unix://...`` that this module starts and
stops: a throw-away HOME/XDG/CODEX_HOME, an allowlisted environment (no credentials, proxy or gateway
variables), no model access, and an exact-PID process group that is always stopped. Two or three
independent clients play the roles of the human-serving surface (A) and the joining observer (B, C).

What this proves is protocol-level: the same native thread is visible to independent clients, an
observer can attach and detach without disturbing the original client, and a fresh client resolves the
same thread. It does NOT prove the Codex TUI shares this session authority, so no human-UI continuity
is claimed, and concurrent human use stays unproven until a human-style client is exercised. Admission and result
attribution are measured with real turns against a local deterministic stub model (loopback, OS-assigned port,
gate-held busy window): they speak to the harness protocol only, never to a vendor model.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.components.providers.adapters.codex.join import (
    REQUIRED_METHODS,
    AppServerClient,
    AppServerError,
    OwnedAppServer,
)

from ..live import CAPABILITIES, LiveContext, ProbeOutcome
from .stub_model import StubModel

PROBE_VERSION = "1"
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM")
_UNPROVEN_NEEDS_HUMAN_UI = "unproven-needs-human-ui-probe"
_SETTLE_SECONDS = 1.5  # how long a departure is observed before the survivor is checked


def disposable_env(root: Path) -> dict[str, str]:
    """An allowlisted environment rooted in the disposable directory: nothing inherited that could carry a credential."""
    home = root / "home"
    for name in ("home", "xdg-config", "xdg-data", "xdg-cache", "xdg-state", "codex-home", "tmp"):
        (root / name).mkdir(parents=True, exist_ok=True)
    env = {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}
    env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(root / "xdg-config"), "XDG_DATA_HOME": str(root / "xdg-data"),
                "XDG_CACHE_HOME": str(root / "xdg-cache"), "XDG_STATE_HOME": str(root / "xdg-state"),
                "CODEX_HOME": str(root / "codex-home"), "TMPDIR": str(root / "tmp")})
    return env


def _protocol_methods(executable: Path, env: dict[str, str], out: Path) -> tuple[set[str], str]:
    """The client-request methods of this exact executable, and the digest of its generated schema."""
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(executable), "app-server", "generate-json-schema", "--out", str(out)],  # noqa: S603
                   env=env, capture_output=True, timeout=120, check=True)
    document = (out / "ClientRequest.json").read_bytes()
    methods: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            method = node.get("method")
            if isinstance(method, dict) and isinstance(method.get("enum"), list):
                methods.update(str(item) for item in method["enum"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json.loads(document))
    return methods, "sha256:" + hashlib.sha256(document).hexdigest()


def _ids(result: dict[str, Any]) -> set[str]:
    """Thread ids from a list-style answer, whether entries are bare ids or objects."""
    found: set[str] = set()
    for item in result.get("data") or []:
        if isinstance(item, str):
            found.add(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            found.add(item["id"])
    return found


def _thread_id(result: dict[str, Any]) -> str | None:
    thread = result.get("thread")
    return thread.get("id") if isinstance(thread, dict) else None


def _failed(name: str, step: str, error: Exception) -> ProbeOutcome:
    detail = {"step": step, "error": getattr(error, "kind", type(error).__name__)}
    if getattr(error, "method", None):
        detail["method"] = error.method
    return ProbeOutcome(name, False, "probe-failed", detail)


def _text_input(text: str) -> list[dict[str, str]]:
    return [{"type": "text", "text": text}]


def _agent_text(notification: dict[str, Any] | None) -> str:
    """The agent message text of a ``turn/completed`` notification (bounded; used only to compare)."""
    items = ((notification or {}).get("params") or {}).get("turn", {}).get("items") or []
    return "|".join(str(item.get("text")) for item in items if item.get("type") == "agentMessage")[:200]


def _completed(turn_id: str):
    return lambda params: (params.get("turn") or {}).get("id") == turn_id


async def _turn_probes(a: AppServerClient, b: AppServerClient, workspace: Path, stub: StubModel,
                       outcomes: dict[str, ProbeOutcome]) -> None:
    """Admission and result attribution, measured with real turns against the local stub model."""
    thread = _thread_id(await a.request("thread/start", {"cwd": str(workspace)}))
    if not thread:
        raise AppServerError("no-thread-id", "thread/start")
    # Idle: one turn from A is admitted exactly once and completes with its own result.
    base = stub.requests
    first = (await a.request("turn/start", {"threadId": thread, "input": _text_input("idle turn"),
                                            "clientUserMessageId": "qualify-idle-1"}))["turn"]["id"]
    done_first = await a.wait_for("turn/completed", 20, match=_completed(first))
    idle_once = done_first is not None and stub.requests == base + 1
    # A second, sequential caller (B) attaches to the now-persisted thread and gets its own turn.
    await b.request("thread/resume", {"threadId": thread})
    second = (await b.request("turn/start", {"threadId": thread, "input": _text_input("idle turn from the observer"),
                                             "clientUserMessageId": "qualify-idle-2"}))["turn"]["id"]
    done_second = await b.wait_for("turn/completed", 20, match=_completed(second))
    text_first, text_second = _agent_text(done_first), _agent_text(done_second)
    idle_attributed = bool(done_second) and first != second and text_first != text_second and bool(text_first) and bool(text_second)
    # Busy: hold A's turn open, then ask B to start a turn on the same thread.
    stub.hold()
    active = (await a.request("turn/start", {"threadId": thread, "input": _text_input("active turn"),
                                             "clientUserMessageId": "qualify-busy-A"}))["turn"]["id"]
    stub.wait_for_requests(base + 3, 20)
    at_active = stub.requests
    expected_text = f"STUB-REPLY-{at_active}"
    intruder = (await b.request("turn/start", {"threadId": thread, "input": _text_input("injected by the observer"),
                                               "clientUserMessageId": "qualify-busy-B"}))["turn"]["id"]
    await asyncio.sleep(1.5)
    extra_requests = stub.requests - at_active
    stub.release()
    done_active = await a.wait_for("turn/completed", 20, match=_completed(active))
    final_text = _agent_text(done_active)
    steered = intruder == active
    unchanged = bool(done_active) and final_text == expected_text and extra_requests == 0
    observations = {
        "idle-admitted-exactly-once": idle_once, "idle-callers-attributed-by-turn-id": idle_attributed,
        "busy-second-caller-got-the-active-turn-id": steered, "model-requests-added-to-the-active-turn": extra_requests,
        "active-turn-output-unchanged": unchanged, "clientUserMessageId-sent": True,
        "stub-unexpected-requests": len(stub.unexpected),
    }
    if stub.unexpected:
        for name in ("conditional-admission", "correlated-result"):
            outcomes[name] = ProbeOutcome(name, False, "probe-failed", {"step": "stub", "unexpected-requests": len(stub.unexpected)})
        return
    admitted_safely = idle_once and not steered and unchanged
    outcomes["conditional-admission"] = ProbeOutcome(
        "conditional-admission", admitted_safely,
        None if admitted_safely else ("unsupported-turn-start-steers-active-turn" if steered or extra_requests else "probe-failed"),
        observations)
    attributed = idle_attributed and not steered
    outcomes["correlated-result"] = ProbeOutcome(
        "correlated-result", attributed,
        None if attributed else ("unsupported-concurrent-callers-share-a-turn" if steered else "probe-failed"),
        {k: observations[k] for k in ("idle-callers-attributed-by-turn-id", "busy-second-caller-got-the-active-turn-id")})


async def _probe(context: LiveContext, env: dict[str, str], executable: Path, stub: StubModel) -> dict[str, ProbeOutcome]:
    workspace = context.root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    socket_path = context.root / "app.sock"
    server = OwnedAppServer(executable, socket_path, env, workspace).start()
    clients: list[AppServerClient] = []
    outcomes: dict[str, ProbeOutcome] = {}

    async def client(name: str) -> AppServerClient:
        connected = await AppServerClient(socket_path, name).connect()
        clients.append(connected)
        await connected.initialize()
        return connected

    try:
        # A is the human-serving surface: it owns the session under test.
        try:
            a = await client("A")
            thread_id = _thread_id(await a.request("thread/start", {"cwd": str(workspace)}))
            if not thread_id:
                raise AppServerError("no-thread-id", "thread/start")
            # A thread without a turn has no persisted rollout, and a rollout is what an observer attaches
            # to. Seed synthetic history (no model call; the content is a fixed label, never a prompt).
            await a.request("thread/inject_items", {"threadId": thread_id, "items": [
                {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "qualification seed"}]}]})
            before = _ids(await a.request("thread/loaded/list"))
        except Exception as error:  # noqa: BLE001 - nothing can be proven without the original session
            return {name: _failed(name, "original-session", error) for name in CAPABILITIES}

        # passive-identity: an independent client sees the same native thread and creates nothing.
        try:
            b = await client("B")
            seen_loaded = _ids(await b.request("thread/loaded/list"))
            read_id = _thread_id(await b.request("thread/read", {"threadId": thread_id}))
            after = _ids(await a.request("thread/loaded/list"))
            ok = thread_id in seen_loaded and read_id == thread_id and after == before
            outcomes["passive-identity"] = ProbeOutcome(
                "passive-identity", ok, None if ok else "probe-failed",
                {"original-visible-to-observer": thread_id in seen_loaded, "read-same-id": read_id == thread_id,
                 "observer-created-nothing": after == before})
        except Exception as error:  # noqa: BLE001
            outcomes["passive-identity"] = _failed("passive-identity", "observe", error)

        # existing-session-attach: the observer attaches to the live thread while A stays operational.
        try:
            attached = _thread_id(await b.request("thread/resume", {"threadId": thread_id}))
            still = _thread_id(await a.request("thread/read", {"threadId": thread_id}))
            ok = attached == thread_id and still == thread_id
            outcomes["existing-session-attach"] = ProbeOutcome(
                "existing-session-attach", ok, None if ok else "probe-failed",
                {"attached-same-id": attached == thread_id, "original-client-operational": still == thread_id})
        except Exception as error:  # noqa: BLE001
            outcomes["existing-session-attach"] = _failed("existing-session-attach", "attach", error)

        # Admission and attribution with real turns (stub model, see the module docstring).
        try:
            await _turn_probes(a, b, workspace, stub, outcomes)
        except Exception as error:  # noqa: BLE001
            for name in ("conditional-admission", "correlated-result"):
                outcomes[name] = _failed(name, "turns", error)
            stub.release()

        # safe-detach has two directions. (1) The observer leaves while the original client stays attached.
        # (2) The ORIGINAL client leaves while an observer is attached (the human closes their UI): the
        # session must survive for the observer. If either fails, detach is not safe.
        try:
            await b.request("thread/unsubscribe", {"threadId": thread_id})
            await b.close()
            observer_alive = server.alive
            observer_loaded = thread_id in _ids(await a.request("thread/loaded/list"))
            observer_readable = _thread_id(await a.request("thread/read", {"threadId": thread_id})) == thread_id
            b2 = await client("B2")
            reattached = _thread_id(await b2.request("thread/resume", {"threadId": thread_id})) == thread_id
            await a.close()  # the human's client goes away while B2 is still attached
            await asyncio.sleep(_SETTLE_SECONDS)
            human_loaded = thread_id in _ids(await b2.request("thread/loaded/list"))
            human_readable = _thread_id(await b2.request("thread/read", {"threadId": thread_id})) == thread_id
            ok = observer_alive and observer_loaded and observer_readable and reattached and human_loaded and human_readable
            outcomes["safe-detach"] = ProbeOutcome(
                "safe-detach", ok, None if ok else "probe-failed",
                {"observer-leaves": {"server-alive": observer_alive, "thread-still-loaded": observer_loaded,
                                     "original-client-operational": observer_readable},
                 "original-leaves": {"observer-reattached": reattached, "thread-still-loaded-for-observer": human_loaded,
                                     "observer-can-read": human_readable}})
            # Informational, not gating: what a last-subscriber departure does to the session.
            await b2.request("thread/unsubscribe", {"threadId": thread_id})
            await asyncio.sleep(_SETTLE_SECONDS)
            last_probe = await client("L")
            last_loaded = thread_id in _ids(await last_probe.request("thread/loaded/list"))
            last_resumable = _thread_id(await last_probe.request("thread/resume", {"threadId": thread_id})) == thread_id
            outcomes["safe-detach"].observations["last-subscriber-leaves"] = {
                "still-loaded-after-seconds": _SETTLE_SECONDS if last_loaded else None, "resumable": last_resumable}
        except Exception as error:  # noqa: BLE001
            if "safe-detach" not in outcomes:
                outcomes["safe-detach"] = _failed("safe-detach", "detach", error)

        # reconnect: a brand-new client resolves the same thread after every earlier client has left.
        try:
            c = await client("C")
            again = thread_id in _ids(await c.request("thread/loaded/list"))
            same = _thread_id(await c.request("thread/read", {"threadId": thread_id})) == thread_id
            ok = again and same
            outcomes["reconnect"] = ProbeOutcome("reconnect", ok, None if ok else "probe-failed",
                                                 {"thread-still-loaded": again, "read-same-id": same})
        except Exception as error:  # noqa: BLE001
            outcomes["reconnect"] = _failed("reconnect", "reconnect", error)
        return outcomes
    finally:
        for connected in clients:
            try:
                await connected.close()
            except Exception:  # noqa: BLE001, S110 - closing a dead client must not hide the result
                pass
        stopped = server.stop()
        for outcome in outcomes.values():
            outcome.observations["server-stopped"] = stopped
            outcome.observations["session-history"] = "synthetic-seed"


def run(context: LiveContext) -> list[ProbeOutcome]:
    """Run every Codex probe in a disposable environment; capabilities without a probe stay unproven."""
    executable = Path(str(context.facts["executable"]))
    env = disposable_env(context.root)
    try:
        methods, schema_digest = _protocol_methods(executable, env, context.root / "schema")
    except Exception as error:  # noqa: BLE001
        return [_failed(name, "schema", error) for name in CAPABILITIES]
    missing = sorted(REQUIRED_METHODS - methods)
    if missing:
        return [ProbeOutcome(name, False, "unsupported-protocol-method-missing",
                             {"missing": missing[:8], "schema-digest": schema_digest}) for name in CAPABILITIES]
    stub = StubModel().start()
    try:
        stub.write_config(context.root / "codex-home", context.root / "workspace")
        (context.root / "workspace").mkdir(parents=True, exist_ok=True)
        outcomes = asyncio.run(_probe(context, env, executable, stub))
    except Exception as error:  # noqa: BLE001
        return [_failed(name, "server", error) for name in CAPABILITIES]
    finally:
        stub.stop()
    result = []
    for name in CAPABILITIES:
        outcome = outcomes.get(name) or ProbeOutcome(name, False, _UNPROVEN_NEEDS_HUMAN_UI, {})
        outcome.observations.setdefault("schema-digest", schema_digest)
        outcome.observations.setdefault("probe-version", PROBE_VERSION)
        result.append(outcome)
    return result
