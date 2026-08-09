"""gpt-auto micro-step ladder — verify each step of a real session in isolation.

Debugging gpt-auto end-to-end has repeatedly meant guessing which of ~15 steps
broke, because a single opaque failure ("TimeoutError", "no response") can come
from any of them. This ladder runs each step as its own checked unit against a
real logged-in browser, in dependency order, reporting pass/fail and elapsed
time per step. When something regresses, the first FAIL names the step.

Requires: Chrome on --remote-debugging-port=9222, signed in to ChatGPT, with
the target project workspace reachable.

    python tests/gpt_auto/test_micro_steps.py            # whole ladder
    python tests/gpt_auto/test_micro_steps.py --from 8   # resume at step 8
    python tests/gpt_auto/test_micro_steps.py --only 5   # one step
    python tests/gpt_auto/test_micro_steps.py --list     # names only

Steps 1-8 are read-only. Step 9+ open a real session and send a real (tiny)
prompt, so they cost a live ChatGPT turn.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROJECT_NAME = "AUDiaGentic"
CDP_URL = "http://127.0.0.1:9222"

# A prompt small enough to answer in one short turn -- these steps prove the
# mechanism works, not that the model is clever.
TINY_PROMPT = "Reply with exactly the word: ACKNOWLEDGED"


@dataclass
class Ctx:
    """Carries state between steps so each builds on the proven previous one."""

    client: object | None = None
    tab_id: str = ""
    tab_url: str = ""
    workspace_url: str = ""
    transport: object | None = None
    session_ref: str = ""
    request_id: str = ""
    notes: dict = field(default_factory=dict)


# ── Steps ─────────────────────────────────────────────────────────────
# Each returns a short human-readable detail string, or raises to fail.


async def step_01_cdp_reachable(ctx: Ctx) -> str:
    """Debug port answers and reports a browser build."""
    import urllib.request

    with urllib.request.urlopen(f"{CDP_URL}/json/version", timeout=5) as fh:
        info = json.loads(fh.read())
    browser = info.get("Browser", "?")
    if not browser:
        raise AssertionError("no Browser field in /json/version")
    return browser


async def step_02_client_connects(ctx: Ctx) -> str:
    """CdpClient spawns its node helper and connects."""
    from audiagentic.components.providers.adapters.gpt_auto.cdp_client import CdpClient

    client = CdpClient(cdp_url=CDP_URL)
    await client.start()
    ctx.client = client
    return "helper started, connected"


async def step_03_list_tabs(ctx: Ctx) -> str:
    """Browser exposes tabs and at least one is ChatGPT."""
    tabs = await ctx.client.list_tabs()
    chat = [t for t in tabs if "chatgpt.com" in t.url.lower()]
    if not chat:
        raise AssertionError(f"no chatgpt.com tab among {len(tabs)} tabs")
    ctx.notes["chat_tabs"] = [t.url for t in chat]
    return f"{len(tabs)} tabs, {len(chat)} ChatGPT"


async def step_04_activate_tab(ctx: Ctx) -> str:
    """A ChatGPT tab can be selected as the helper's active page.

    Prefers a workspace tab; falls back to any ChatGPT tab.
    """
    tabs = await ctx.client.list_tabs()
    target = next(
        (t for t in tabs if "chatgpt.com" in t.url.lower() and "/g/g-p-" in t.url.lower()), None
    ) or next((t for t in tabs if "chatgpt.com" in t.url.lower()), None)
    if target is None:
        raise AssertionError("no ChatGPT tab to activate")
    result = await ctx.client.activate_tab(target.tab_id)
    if not result:
        raise AssertionError(f"activate_tab returned falsy for {target.tab_id}")
    ctx.tab_id, ctx.tab_url = target.tab_id, result.url
    return result.url[:70]


async def step_05_evaluate_works(ctx: Ctx) -> str:
    """JS evaluation round-trips against the active page."""
    got = await ctx.client.evaluate("() => 6 * 7")
    if got != 42:
        raise AssertionError(f"expected 42, got {got!r}")
    return "evaluate round-trip ok"


async def step_06_keep_page_active(ctx: Ctx) -> str:
    """Focus/visibility emulation applies and the page believes it.

    This is the precondition for streaming to survive an occluded window; if
    it regresses, long answers die after their first chunk.
    """
    applied = await ctx.client.keep_page_active()
    if not applied.get("ok"):
        raise AssertionError(f"keep_page_active reported not-ok: {applied}")
    state = await ctx.client.evaluate(
        "() => ({f: document.hasFocus(), v: document.visibilityState})"
    )
    if not state.get("f") or state.get("v") != "visible":
        raise AssertionError(f"page still not focused/visible after emulation: {state}")
    return f"{applied.get('applied')} -> {state}"


async def step_07_logged_in(ctx: Ctx) -> str:
    """The browser is signed in: no login page, and a composer exists.

    gpt-auto never drives a sign-in, so this is a precondition, not a step it
    can recover from.
    """
    from audiagentic.components.providers.adapters.gpt_auto.prompt_injector import (
        _IS_LOGIN_PAGE_JS,
    )

    page_state = await ctx.client.evaluate_resilient(_IS_LOGIN_PAGE_JS)
    if page_state == "login":
        raise AssertionError("login page detected — sign in to ChatGPT first")
    return f"page_state={page_state!r}"


async def step_08_resolve_workspace(ctx: Ctx) -> str:
    """The project workspace resolves (reusing the mapped tab when possible)."""
    from audiagentic.components.providers.adapters.gpt_auto.workspace import ensure_workspace

    ws = await ensure_workspace(ctx.client, PROJECT_NAME, project_root=REPO_ROOT)
    if ws is None:
        raise AssertionError(f"workspace {PROJECT_NAME!r} not found")
    ctx.workspace_url = ws.url
    return ws.url[:70]


async def step_09_chatgpt_ready(ctx: Ctx) -> str:
    """The composer is present, so a prompt can actually be injected."""
    from audiagentic.components.providers.adapters.gpt_auto.prompt_injector import (
        wait_for_chatgpt_ready,
    )

    ready = await wait_for_chatgpt_ready(ctx.client, timeout=15.0, login_timeout=20.0)
    if not ready:
        raise AssertionError("wait_for_chatgpt_ready returned False")
    return "composer present"


async def step_10_dom_read_primitives(ctx: Ctx) -> str:
    """Response-state and generating predicates evaluate without error.

    Value correctness is not asserted (the page may legitimately be mid-turn);
    what matters is that both predicates run and return sane types.
    """
    from audiagentic.components.providers.adapters.gpt_auto.dom_reader import (
        _get_response_state,
        is_generating,
    )

    count, text = await _get_response_state(ctx.client)
    gen = await is_generating(ctx.client)
    if not isinstance(count, int) or not isinstance(gen, bool):
        raise AssertionError(f"bad types: count={count!r} gen={gen!r}")
    ctx.notes["baseline_blocks"] = count
    return f"blocks={count} text_len={len(text or '')} generating={gen}"


async def step_11_transport_open(ctx: Ctx) -> str:
    """The real transport opens a session end to end, with a real config.

    Uses GptAutoConfig explicitly: config values override the function-signature
    defaults, and a stale config default previously caused opens to fail at
    exactly the 120s session-open budget.
    """
    from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
    from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
        build_gpt_auto_session_transport,
    )

    transport = build_gpt_auto_session_transport(REPO_ROOT, config=GptAutoConfig())
    result = await transport.open()
    ctx.transport = transport
    ctx.session_ref = getattr(result, "ag_session_id", "") or str(result)
    return f"ref={ctx.session_ref[:60]}"


async def _turn(ctx: Ctx, turn_id: str, body: str):
    """Run one real turn and return (result, observation_count)."""
    from audiagentic.foundation.transports.agent_session import SessionPrompt

    class _Sink:
        def __init__(self):
            self.seen = 0

        async def deliver(self, _obs):
            self.seen += 1

        # The sink protocol has varied; accept either name so a rename shows up
        # as "0 observations" rather than an exception that masks the turn.
        async def __call__(self, _obs):
            self.seen += 1

    sink = _Sink()
    result = await ctx.transport.prompt(SessionPrompt(turn_id=turn_id, body=body), sink)
    if result.stop_reason != "end_turn":
        raise AssertionError(f"stop_reason={result.stop_reason!r} (expected end_turn)")
    if not result.final_summary:
        raise AssertionError("turn produced no text")
    return result, sink.seen


async def step_12_transport_prompt(ctx: Ctx) -> str:
    """One real turn completes through the transport and returns text."""
    result, seen = await _turn(ctx, "micro-turn-1", TINY_PROMPT)
    ctx.notes["turn1_text"] = result.final_summary
    meta = result.metadata or {}
    ctx.notes["chat_url"] = meta.get("chat-url") or ""
    ctx.notes["chat_id"] = meta.get("chat-id") or ""
    return f"{len(result.final_summary)} chars, {seen} observations, chat={ctx.notes['chat_id'] or '?'}"


async def step_13_second_turn_is_distinct(ctx: Ctx) -> str:
    """A second turn in the SAME session returns its own answer.

    Regression guard for the stale-read failure where turn 2 returned turn 1's
    text verbatim: the reader locked onto the previous assistant block instead
    of waiting for the new one. Asking a question with a different answer makes
    that failure unambiguous rather than a judgement call.
    """
    result, seen = await _turn(ctx, "micro-turn-2", "Reply with exactly the word: CONFIRMED")
    first = ctx.notes.get("turn1_text", "")
    if result.final_summary.strip() == first.strip():
        raise AssertionError(
            f"turn 2 returned turn 1's text verbatim ({first[:40]!r}) — stale read"
        )
    ctx.notes["turn2_text"] = result.final_summary
    return f"distinct: turn1={first.strip()[:20]!r} turn2={result.final_summary.strip()[:20]!r}"


async def step_14_conversation_continuity(ctx: Ctx) -> str:
    """Both turns landed in one conversation, not separate chats."""
    from audiagentic.components.providers.adapters.gpt_auto.dom_reader import (
        _get_response_state,
    )

    count, _ = await _get_response_state(ctx.transport._client)
    baseline = ctx.notes.get("baseline_blocks", 0)
    if count < baseline + 2:
        raise AssertionError(
            f"expected >= {baseline + 2} assistant blocks after 2 turns, saw {count}"
        )
    ctx.notes["blocks_after_two"] = count
    return f"{count} assistant blocks (baseline {baseline})"


async def step_15_transport_close(ctx: Ctx) -> str:
    """The transport closes cleanly and releases its helper."""
    await ctx.transport.close()
    ctx.transport = None
    return "closed"


async def step_16_resume_same_conversation(ctx: Ctx) -> str:
    """Reopening with a resume ref returns to the SAME conversation.

    The distinction that matters: resume must continue the existing chat, not
    silently start a fresh one that merely looks similar.
    """
    from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
    from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
        build_gpt_auto_session_transport,
    )

    chat_id = ctx.notes.get("chat_id") or ""
    if not chat_id:
        raise AssertionError("no conversation id captured from turn 1 — cannot test resume")

    transport = build_gpt_auto_session_transport(
        REPO_ROOT, config=GptAutoConfig(), resume_provider_ref=chat_id
    )
    result = await transport.open()
    ctx.transport = transport
    ref = getattr(result, "ag_session_id", "") or str(result)
    url = await transport._client.get_url()
    if chat_id not in url:
        raise AssertionError(f"resumed to {url!r}, expected conversation {chat_id!r}")
    return f"resumed conversation {chat_id[:18]}… ref={ref[:40]}"


async def step_17_turn_in_resumed_session(ctx: Ctx) -> str:
    """A turn in the resumed session works and stays in that conversation."""
    result, seen = await _turn(ctx, "micro-turn-3", "Reply with exactly the word: RESUMED")
    prior = {ctx.notes.get("turn1_text", "").strip(), ctx.notes.get("turn2_text", "").strip()}
    if result.final_summary.strip() in prior:
        raise AssertionError("resumed turn returned an earlier turn's text — stale read")
    url = await ctx.transport._client.get_url()
    chat_id = ctx.notes.get("chat_id", "")
    if chat_id and chat_id not in url:
        raise AssertionError(f"resumed turn drifted to a different chat: {url!r}")
    await ctx.transport.close()
    ctx.transport = None
    return f"{len(result.final_summary)} chars, {seen} observations, same chat"


async def step_18_new_session_is_fresh(ctx: Ctx) -> str:
    """Opening WITHOUT a resume ref starts a new chat, not the resumed one.

    The inverse of step 16 -- proves the two paths are genuinely distinct
    rather than both landing on whatever the tab happened to show.
    """
    from audiagentic.components.providers.adapters.gpt_auto.config import GptAutoConfig
    from audiagentic.components.providers.adapters.gpt_auto.session_transport import (
        build_gpt_auto_session_transport,
    )

    transport = build_gpt_auto_session_transport(REPO_ROOT, config=GptAutoConfig())
    await transport.open()
    ctx.transport = transport
    url = await transport._client.get_url()
    await transport.close()
    ctx.transport = None

    old_chat = ctx.notes.get("chat_id", "")
    # A new session lands on the project's new-chat page; it must not resume
    # the previous conversation.
    if old_chat and old_chat in url:
        raise AssertionError(f"new session reused the previous conversation {old_chat!r}")
    return f"fresh landing {url[-40:]!r} (not {old_chat[:18] or 'n/a'}…)"


def step_19_provider_prepare(ctx: Ctx):
    """The provider prepare seam resolves a transport for the CDP surface.

    Synchronous, and called from inside the SessionRuntime coroutine -- so if
    it is ever slow it blocks that whole event loop, not just its own caller.
    """
    from audiagentic.components.providers import providers_api
    from audiagentic.components.providers.providers_api import SurfaceHint

    prepared = providers_api.prepare_provider_session_transport(
        REPO_ROOT,
        provider_id="gpt-auto",
        surface_hint=SurfaceHint(surface_id="gpt-auto-cdp"),
        model_id="chatgpt",
    )
    if prepared.transport is None:
        raise AssertionError("prepare returned no transport for gpt-auto-cdp")
    return f"transport={type(prepared.transport).__name__}"


async def step_20_session_runtime_open(ctx: Ctx) -> str:
    """SessionRuntime.open_session() -- the layer the gateway actually calls.

    Distinct from step 11: this wraps transport.open() with the provider
    prepare seam, session-record persistence and binding registration, and runs
    it on the runtime's own loop thread via _call(). Steps 11-18 all bypass
    this, so a fault here is invisible to them while breaking every real
    gateway submit.
    """
    from audiagentic.components.agents.gateway.session.sessions import SessionRuntime

    runtime = SessionRuntime()
    try:
        record = runtime.open_session(
            REPO_ROOT,
            execution_profile_id="gpt-auto",
            provider_id="gpt-auto",
            model_id="chatgpt",
            surface_hint=_cdp_surface_hint(),
        )
        session_id = record["session-id"]
        ctx.notes["runtime_session_id"] = session_id
        try:
            runtime.close_session(REPO_ROOT, session_id)
        except Exception:
            pass
        return f"opened+closed {session_id}"
    finally:
        try:
            runtime.shutdown()
        except Exception:
            pass


def _cdp_surface_hint():
    from audiagentic.components.providers.providers_api import SurfaceHint

    return SurfaceHint(surface_id="gpt-auto-cdp")


async def step_21_agent_definition_resolves(ctx: Ctx) -> str:
    """The gateway-facing agent definition composes profile + role.

    Pure config resolution -- no browser -- but it gates every gateway submit,
    so a break here looks like a provider failure.
    """
    from audiagentic.components.agents.models.agent_definition_api import (
        resolve_agent_definition,
    )

    resolved = resolve_agent_definition(REPO_ROOT, "gpt-auto-reviewer-agent")
    profile = resolved["execution_profile"]
    if profile["provider_id"] != "gpt-auto":
        raise AssertionError(f"unexpected provider {profile['provider_id']!r}")
    return f"{resolved['agent_id']} -> {profile['provider_id']}/{profile['instances']} role={resolved['role']['role_id']}"


async def step_22_instance_resolves(ctx: Ctx) -> str:
    """Profile instances resolve to dispatchable facts (AS105/AS101 path)."""
    from audiagentic.components.agents.gateway.instances import resolve_instance_facts

    facts = resolve_instance_facts(REPO_ROOT, ("chatgpt",))
    if not facts or facts[0].model_id != "chatgpt":
        raise AssertionError(f"unexpected instance facts: {facts}")
    return f"{facts[0].source_id} -> model={facts[0].model_id} gated={facts[0].resource_id is not None}"


STEPS = [
    step_01_cdp_reachable,
    step_02_client_connects,
    step_03_list_tabs,
    step_04_activate_tab,
    step_05_evaluate_works,
    step_06_keep_page_active,
    step_07_logged_in,
    step_08_resolve_workspace,
    step_09_chatgpt_ready,
    step_10_dom_read_primitives,
    step_11_transport_open,
    step_12_transport_prompt,
    step_13_second_turn_is_distinct,
    step_14_conversation_continuity,
    step_15_transport_close,
    step_16_resume_same_conversation,
    step_17_turn_in_resumed_session,
    step_18_new_session_is_fresh,
    step_19_provider_prepare,
    step_20_session_runtime_open,
    step_21_agent_definition_resolves,
    step_22_instance_resolves,
]


async def run(selected: list[int]) -> int:
    ctx = Ctx()
    failures = 0
    print(f"{'#':>3}  {'step':38s} {'time':>8s}  result")
    print("-" * 100)
    for index, fn in enumerate(STEPS, start=1):
        if index not in selected:
            continue
        name = fn.__name__.split("_", 2)[2]
        t0 = time.monotonic()
        try:
            result = fn(ctx)
            detail = await result if asyncio.iscoroutine(result) else result
            print(f"{index:3d}  {name:38s} {time.monotonic()-t0:7.2f}s  PASS  {detail}")
        except Exception as exc:  # noqa: BLE001 -- a ladder reports, it does not raise
            failures += 1
            print(f"{index:3d}  {name:38s} {time.monotonic()-t0:7.2f}s  FAIL  {type(exc).__name__}: {exc}")
            if "-v" in sys.argv:
                traceback.print_exc()
            # Later steps build on earlier ones; continuing past a failure
            # produces cascading noise that hides the real first cause.
            print("\nstopping at first failure (later steps depend on it)")
            break

    # Best-effort teardown so a failed run does not leak a helper or session.
    if ctx.transport is not None:
        try:
            await ctx.transport.close()
        except Exception:
            pass
    elif ctx.client is not None:
        try:
            await ctx.client.stop()
        except Exception:
            pass

    print("-" * 100)
    print("ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=1)
    ap.add_argument("--only", type=int, default=None)
    ap.add_argument("--to", type=int, default=len(STEPS))
    ap.add_argument("--list", action="store_true")
    args, _ = ap.parse_known_args()

    if args.list:
        for i, fn in enumerate(STEPS, start=1):
            print(f"{i:3d}  {fn.__name__.split('_', 2)[2]}")
        return 0

    selected = [args.only] if args.only else list(range(args.start, args.to + 1))
    return asyncio.run(run(selected))


if __name__ == "__main__":
    raise SystemExit(main())
