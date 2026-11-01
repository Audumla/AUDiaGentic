"""Codex app-server native probes (SH54-A): identity, attach, detach and reconnect over the real protocol.

Each probe talks to a DISPOSABLE ``codex app-server --listen unix://...`` that this module starts and
stops: a throw-away HOME/XDG/CODEX_HOME, an allowlisted environment (no credentials, proxy or gateway
variables), no model access, and an exact-PID process group that is always stopped. Two or three
independent clients play the roles of the human-serving surface (A) and the joining observer (B, C).

What this proves is protocol-level: the same native thread is visible to independent clients, an
observer can attach and detach without disturbing the original client, and a fresh client resolves the
same thread. It does NOT prove the Codex TUI shares this session authority, so no human-UI continuity
is claimed, and turn-dependent capabilities (conditional admission, correlated results, concurrent
human use) are left unproven until a turn probe exists.
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

PROBE_VERSION = "1"
_ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM")
_UNPROVEN_NEEDS_TURNS = "unproven-needs-turn-probe"


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


async def _probe(context: LiveContext, env: dict[str, str], executable: Path) -> dict[str, ProbeOutcome]:
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

        # safe-detach: the observer leaves; the original session, client and server are undisturbed.
        try:
            await b.request("thread/unsubscribe", {"threadId": thread_id})
            await b.close()
            alive = server.alive
            loaded = thread_id in _ids(await a.request("thread/loaded/list"))
            readable = _thread_id(await a.request("thread/read", {"threadId": thread_id})) == thread_id
            ok = alive and loaded and readable
            outcomes["safe-detach"] = ProbeOutcome(
                "safe-detach", ok, None if ok else "probe-failed",
                {"server-alive": alive, "thread-still-loaded": loaded, "original-client-operational": readable})
        except Exception as error:  # noqa: BLE001
            outcomes["safe-detach"] = _failed("safe-detach", "detach", error)

        # reconnect: a brand-new client resolves the same thread afterwards.
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
    try:
        outcomes = asyncio.run(_probe(context, env, executable))
    except Exception as error:  # noqa: BLE001
        return [_failed(name, "server", error) for name in CAPABILITIES]
    result = []
    for name in CAPABILITIES:
        outcome = outcomes.get(name) or ProbeOutcome(name, False, _UNPROVEN_NEEDS_TURNS, {})
        outcome.observations.setdefault("schema-digest", schema_digest)
        outcome.observations.setdefault("probe-version", PROBE_VERSION)
        result.append(outcome)
    return result
